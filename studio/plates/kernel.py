"""The plate generator: still pictures for backgrounds, made on Kaggle's free GPUs (pushed there by studio/plates_gen.py,
which writes the JOBS and CFG lines below). Never run on GitHub Actions.

Model: Stable Diffusion XL base 1.0 (Stability AI, CreativeML Open RAIL++-M: commercial use allowed, with its use
restrictions) and the fp16-safe SDXL VAE (madebyollin, MIT), fp16 on T4s. One worker per GPU, each with its own copy of
the pipeline. Every picture is checked (not black, not blank) and written to /kaggle/working/plates/<job id>.jpg with a
line in manifest.json.
"""
import json, os, queue, subprocess, sys, time, traceback
import multiprocessing as mp

JOBS = []   # written by studio/plates_gen.py: [{"id", "theme", "scene", "look", "prompt", "seed"}]
CFG = {}    # written by studio/plates_gen.py: {"batch", "hours", "steps", "width", "height", "guidance", "negative"}

OUT = '/kaggle/working'; PLATES = os.path.join(OUT, 'plates')
T0 = time.time()
MODEL = 'stabilityai/stable-diffusion-xl-base-1.0'; VAE = 'madebyollin/sdxl-vae-fp16-fix'


def log(*a):
    print('[%6.0fs]' % (time.time() - T0), *a, flush=True)


def gpus():
    try: r = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'], capture_output=True, text=True)
    except FileNotFoundError: return []
    out = []
    for line in r.stdout.strip().splitlines():
        name, mib = [x.strip() for x in line.rsplit(',', 1)]; out.append((name, int(float(mib))))
    return out


def worker(gpu, jobs, q):
    os.environ['CUDA_VISIBLE_DEVICES'] = str(gpu)
    try:
        import numpy as np, torch
        from diffusers import AutoencoderKL, DPMSolverMultistepScheduler, StableDiffusionXLPipeline
        vae = AutoencoderKL.from_pretrained(VAE, torch_dtype=torch.float16)
        pipe = StableDiffusionXLPipeline.from_pretrained(MODEL, vae=vae, torch_dtype=torch.float16, variant='fp16', use_safetensors=True)
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, use_karras_sigmas=True)
        pipe.to('cuda'); pipe.set_progress_bar_config(disable=True)
        took = []
        for j in jobs:
            left = CFG['hours'] * 3600 - (time.time() - T0)
            if took and left < 1.5 * max(took) + 240:
                log('gpu %d: stopping, %.0f min left' % (gpu, left / 60)); break
            t = time.time()
            try:
                g = torch.Generator('cuda').manual_seed(int(j['seed']))
                im = pipe(prompt=j['prompt'], negative_prompt=CFG['negative'], width=CFG['width'], height=CFG['height'],
                          num_inference_steps=CFG['steps'], guidance_scale=CFG['guidance'], generator=g).images[0]
                a = np.asarray(im).astype(np.float32) / 255
                mean, spread = float(a.mean()), float(a.std())
                ok = 0.04 < mean < 0.97 and spread > 0.04
                path = os.path.join(PLATES, j['id'] + '.jpg')
                if ok: im.save(path, quality=94)
                sec = time.time() - t; took.append(sec)
                q.put(('plate', dict(j, file=os.path.basename(path) if ok else None, ok=ok, mean=round(mean, 3), spread=round(spread, 3),
                                     seconds=round(sec), gpu=gpu, model=MODEL, steps=CFG['steps'])))
                log('gpu %d: %s %s in %.0fs' % (gpu, j['id'], 'ok' if ok else 'REJECTED', sec))
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache(); q.put(('plate', dict(j, ok=False, error='out of memory', gpu=gpu))); log('gpu %d: OOM on %s' % (gpu, j['id']))
        q.put(('done', gpu))
    except Exception:
        q.put(('error', traceback.format_exc())); q.put(('done', gpu))


def main():
    os.makedirs(PLATES, exist_ok=True)
    cards = gpus(); log('gpus:', cards)
    if not cards: sys.exit('no GPU: Kaggle gave this run none (the account must be phone-verified, and have GPU hours left)')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-U', 'diffusers==0.43.0', 'accelerate', 'safetensors'], check=True)
    from huggingface_hub import snapshot_download
    snapshot_download(MODEL, allow_patterns=['*.json', '*.txt', 'tokenizer*/*', '*fp16.safetensors'])
    snapshot_download(VAE); log('weights ready')
    ctx = mp.get_context('fork'); q = ctx.Queue()
    shares = [JOBS[k::len(cards)] for k in range(len(cards))]
    procs = [ctx.Process(target=worker, args=(g, shares[g], q)) for g in range(len(cards))]
    for w in procs: w.start()
    made, done, errors = [], set(), []
    while len(done) < len(procs):
        try: kind, x = q.get(timeout=30)
        except queue.Empty:
            for g, w in enumerate(procs):
                if w.exitcode is not None and g not in done:
                    done.add(g); errors.append('gpu %d worker died (exit %s)' % (g, w.exitcode)); log(errors[-1])
            continue
        if kind == 'plate': made.append(x)
        elif kind == 'error': errors.append(x); log(x)
        elif kind == 'done': done.add(x)
        json.dump(dict(batch=CFG['batch'], model=MODEL, gpus=cards, cfg={k: v for k, v in CFG.items() if k != 'negative'},
                       plates=made, errors=errors, seconds=round(time.time() - T0)), open(os.path.join(OUT, 'manifest.json'), 'w'), indent=1)
    for w in procs: w.join()
    log('made %d of %d plates' % (sum(1 for c in made if c.get('ok')), len(JOBS)))


if __name__ == '__main__':
    main()
