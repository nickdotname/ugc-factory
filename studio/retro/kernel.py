"""retro.vibes.arcade's clip generator. Runs on Kaggle's free GPUs (pushed there by studio/retro_gen.py), never on
GitHub Actions: it is a Kaggle "script" kernel, and retro_gen.py writes the JOBS and CFG lines below before pushing.

The model is Wan 2.1 text-to-video 1.3B (Wan-AI, Apache 2.0: the clips are ours to use), run with diffusers. On a
GPU with 40 GB or more it would use Wan 2.2 TI2V 5B instead; Kaggle's free tier gives two T4s, so in practice it is
the 1.3B model at 480x832, one worker per GPU.

The parent process never touches CUDA. It downloads the weights, then forks: one child turns every prompt into
text embeddings (the 11 GB text encoder, spread over both GPUs) and exits, freeing them; then one child per GPU
loads only the video model and the VAE and works through its share of the jobs. Each clip is checked (not black,
not frozen) and written to /kaggle/working/clips/<job id>.mp4 with a line in manifest.json.
"""
import json, os, queue, subprocess, sys, time, traceback
import multiprocessing as mp

JOBS = []   # written by studio/retro_gen.py: [{"id", "prompt", "seed", ...}]
CFG = {}    # written by studio/retro_gen.py: {"batch", "hours", "steps", "frames", "width", "height", "guidance", "negative"}

OUT = '/kaggle/working'; CLIPS = os.path.join(OUT, 'clips'); EMB = '/kaggle/tmp/emb'
T0 = time.time()
SMALL = 'Wan-AI/Wan2.1-T2V-1.3B-Diffusers'; BIG = 'Wan-AI/Wan2.2-TI2V-5B-Diffusers'


def log(*a):
    print('[%6.0fs]' % (time.time() - T0), *a, flush=True)


def gpus():
    """(name, MiB) per GPU, read with nvidia-smi so this process never starts CUDA (the children fork from it)."""
    r = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'], capture_output=True, text=True)
    out = []
    for line in r.stdout.strip().splitlines():
        name, mib = [x.strip() for x in line.rsplit(',', 1)]; out.append((name, int(float(mib))))
    return out


def encode(mid, prompts, negative, q):
    try:
        import torch
        from diffusers import WanPipeline
        from transformers import AutoTokenizer, UMT5EncoderModel
        n = torch.cuda.device_count()
        te = UMT5EncoderModel.from_pretrained(mid, subfolder='text_encoder', torch_dtype=torch.bfloat16,
                                              device_map='auto' if n > 1 else None)
        if n == 1: te = te.to('cuda')
        tok = AutoTokenizer.from_pretrained(mid, subfolder='tokenizer')
        pipe = WanPipeline(tokenizer=tok, text_encoder=te.eval(), vae=None, scheduler=None, transformer=None)
        os.makedirs(EMB, exist_ok=True)
        with torch.no_grad():
            neg, _ = pipe.encode_prompt(negative, None, do_classifier_free_guidance=False, max_sequence_length=512, device='cpu', dtype=torch.float32)
            torch.save(neg, os.path.join(EMB, 'negative.pt'))
            for k, p in enumerate(prompts):
                e, _ = pipe.encode_prompt(p, None, do_classifier_free_guidance=False, max_sequence_length=512, device='cpu', dtype=torch.float32)
                if not torch.isfinite(e).all(): raise RuntimeError('text encoder gave non-finite values (bf16 on this GPU?)')
                torch.save(e, os.path.join(EMB, '%d.pt' % k))
        log('encoded %d prompts' % len(prompts)); q.put(('encoded', None))
    except Exception:
        q.put(('error', traceback.format_exc()))


def worker(gpu, mid, jobs, prompt_index, q):
    os.environ['CUDA_VISIBLE_DEVICES'] = str(gpu)
    try:
        import numpy as np, torch, imageio
        from diffusers import AutoencoderKLWan, WanPipeline, WanTransformer3DModel
        from diffusers.schedulers.scheduling_unipc_multistep import UniPCMultistepScheduler
        big = mid == BIG
        dt = torch.bfloat16 if big else torch.float16          # T4s have no fast bf16; the 1.3B model is fine in fp16
        vae = AutoencoderKLWan.from_pretrained(mid, subfolder='vae', torch_dtype=torch.float32)
        tr = WanTransformer3DModel.from_pretrained(mid, subfolder='transformer', torch_dtype=dt)
        pipe = WanPipeline.from_pretrained(mid, vae=vae, transformer=tr, text_encoder=None, tokenizer=None, torch_dtype=dt)
        pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config, flow_shift=3.0 if not big else 5.0)
        pipe.to('cuda'); pipe.vae.enable_tiling()
        neg = torch.load(os.path.join(EMB, 'negative.pt')).to('cuda', dt)
        took = []
        for j in jobs:
            left = CFG['hours'] * 3600 - (time.time() - T0)
            if took and left < 1.3 * max(took) + 300:
                log('gpu %d: stopping, %.0f min left' % (gpu, left / 60)); break
            t = time.time()
            try:
                pe = torch.load(os.path.join(EMB, '%d.pt' % prompt_index[j['prompt']])).to('cuda', dt)
                g = torch.Generator('cuda').manual_seed(int(j['seed']))
                fr = pipe(prompt_embeds=pe, negative_prompt_embeds=neg, height=CFG['height'], width=CFG['width'],
                          num_frames=CFG['frames'], num_inference_steps=CFG['steps'], guidance_scale=CFG['guidance'],
                          generator=g, output_type='np').frames[0]
                fr = np.nan_to_num(np.asarray(fr, np.float32))
                mean = float(fr.mean()); move = float(np.abs(np.diff(fr[::4], axis=0)).mean()) if len(fr) > 4 else 0.0
                ok = mean > 0.03 and move > 0.004
                path = os.path.join(CLIPS, j['id'] + '.mp4')
                if ok:
                    w = imageio.get_writer(path, fps=CFG.get('fps', 16), codec='libx264', quality=None,
                                           ffmpeg_params=['-crf', '14', '-preset', 'slow'])
                    for f in fr: w.append_data((np.clip(f, 0, 1) * 255).round().astype(np.uint8))
                    w.close()
                sec = time.time() - t; took.append(sec)
                q.put(('clip', dict(j, file=os.path.basename(path) if ok else None, ok=ok, mean=round(mean, 4), motion=round(move, 5),
                                    seconds=round(sec), gpu=gpu, model=mid, steps=CFG['steps'])))
                log('gpu %d: %s %s in %.0fs (mean %.3f, motion %.4f)' % (gpu, j['id'], 'ok' if ok else 'REJECTED', sec, mean, move))
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache(); q.put(('clip', dict(j, ok=False, error='out of memory', gpu=gpu))); log('gpu %d: OOM on %s' % (gpu, j['id']))
        q.put(('done', gpu))
    except Exception:
        q.put(('error', traceback.format_exc())); q.put(('done', gpu))


def main():
    os.makedirs(CLIPS, exist_ok=True)
    cards = gpus(); log('gpus:', cards)
    if not cards: sys.exit('no GPU: the kernel must run with an accelerator')
    mid = BIG if min(m for _, m in cards) >= 40000 else SMALL
    if mid == BIG:                                              # TI2V-5B is trained at 704x1280: keep the vertical frame, scale it up
        CFG.update(width=704, height=1280, frames=min(CFG.get('frames', 81), 121), fps=24)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-U', 'diffusers==0.43.0', 'accelerate', 'ftfy', 'imageio', 'imageio-ffmpeg', 'sentencepiece'], check=True)
    from huggingface_hub import snapshot_download
    snapshot_download(mid); log('weights ready:', mid)
    prompts = sorted({j['prompt'] for j in JOBS}); index = {p: k for k, p in enumerate(prompts)}
    ctx = mp.get_context('fork'); q = ctx.Queue()
    p = ctx.Process(target=encode, args=(mid, prompts, CFG['negative'], q)); p.start()
    while True:                                                 # a child the system kills sends nothing: watch it too
        try: kind, err = q.get(timeout=30); break
        except queue.Empty:
            if p.exitcode is not None: kind, err = 'error', 'the text encoder process died (exit %s): out of memory?' % p.exitcode; break
    p.join()
    if kind == 'error': log(err); sys.exit('text encoding failed')
    shares = [JOBS[k::len(cards)] for k in range(len(cards))]
    procs = [ctx.Process(target=worker, args=(g, mid, shares[g], index, q)) for g in range(len(cards))]
    for w in procs: w.start()
    made, done, errors = [], set(), []
    while len(done) < len(procs):
        try: kind, x = q.get(timeout=30)
        except queue.Empty:
            for g, w in enumerate(procs):
                if w.exitcode is not None and g not in done:
                    done.add(g); errors.append('gpu %d worker died (exit %s)' % (g, w.exitcode)); log(errors[-1])
            continue
        if kind == 'clip': made.append(x)
        elif kind == 'error': errors.append(x); log(x)
        elif kind == 'done': done.add(x)
        json.dump(dict(batch=CFG['batch'], model=mid, gpus=cards, cfg={k: v for k, v in CFG.items() if k != 'negative'},
                       clips=made, errors=errors, seconds=round(time.time() - T0)), open(os.path.join(OUT, 'manifest.json'), 'w'), indent=1)
    for w in procs: w.join()
    log('made %d of %d clips' % (sum(1 for c in made if c.get('ok')), len(JOBS)))


if __name__ == '__main__':
    main()
