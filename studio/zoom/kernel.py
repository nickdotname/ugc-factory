"""Infinite-zoom chains for the zoom account. Runs on Kaggle's free GPUs (pushed there by studio/zoom_gen.py), never on
GitHub Actions; zoom_gen.py writes the JOBS and CFG lines below before pushing.

A chain is a list of top-down scenes from the widest to the closest. The closest picture is made first with SDXL
base (OpenRAIL++: the pictures are ours to use). Then, layer by layer outwards, the previous picture is shrunk to
the middle half of a new canvas and SDXL inpainting paints the border around it to the next, wider prompt. After
each inpaint the shrunk picture is pasted back exactly, so the middle half of layer k+1 IS layer k: zooming in 2x
lands on the next picture with nothing changing. Each GPU works through its own share of the chains.
Writes /kaggle/working/chains/<id>/<k>.jpg (k = 0 closest) and manifest.json.
"""
import json, os, subprocess, sys, time, traceback
import multiprocessing as mp

JOBS = []   # [{"id", "theme", "prompts": [widest .. closest], "seed"}]
CFG = {}    # {"batch", "hours", "steps", "width", "height", "guidance", "style", "negative", "feather"}

OUT = '/kaggle/working'; CH = os.path.join(OUT, 'chains'); T0 = time.time()
BASE = 'stabilityai/stable-diffusion-xl-base-1.0'; INPAINT = 'diffusers/stable-diffusion-xl-1.0-inpainting-0.1'


def log(*a):
    print('[%6.0fs]' % (time.time() - T0), *a, flush=True)


def gpus():
    try: r = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'], capture_output=True, text=True)
    except FileNotFoundError: return 0
    return len([l for l in r.stdout.splitlines() if l.strip()])


def worker(gpu, jobs, q):
    os.environ['CUDA_VISIBLE_DEVICES'] = str(gpu)
    try:
        import numpy as np, torch
        from PIL import Image, ImageFilter
        from diffusers import StableDiffusionXLPipeline, StableDiffusionXLInpaintPipeline, AutoencoderKL
        vae = AutoencoderKL.from_pretrained('madebyollin/sdxl-vae-fp16-fix', torch_dtype=torch.float16)   # the stock SDXL VAE overflows in fp16
        base = StableDiffusionXLPipeline.from_pretrained(BASE, vae=vae, torch_dtype=torch.float16, variant='fp16', use_safetensors=True).to('cuda')
        inp = StableDiffusionXLInpaintPipeline.from_pretrained(INPAINT, vae=vae, torch_dtype=torch.float16, variant='fp16', use_safetensors=True).to('cuda')
        base.enable_vae_tiling(); inp.enable_vae_tiling()
        W, H, fe = CFG['width'], CFG['height'], CFG.get('feather', 40)
        took = []
        for j in jobs:
            left = CFG['hours'] * 3600 - (time.time() - T0)
            if took and left < 1.3 * max(took) + 300: log('gpu %d: stopping, %.0f min left' % (gpu, left / 60)); break
            t = time.time(); d = os.path.join(CH, j['id']); os.makedirs(d, exist_ok=True)
            try:
                ps = list(reversed(j['prompts']))                  # closest first
                g = torch.Generator('cuda').manual_seed(int(j['seed']))
                def full(p): return '%s, %s' % (p, CFG['style'])
                img = base(prompt=full(ps[0]), negative_prompt=CFG['negative'], width=W, height=H, num_inference_steps=CFG['steps'],
                           guidance_scale=CFG['guidance'], generator=g).images[0]
                img.save(os.path.join(d, '0.jpg'), quality=95); layers = [img]
                for k, p in enumerate(ps[1:], 1):
                    small = layers[-1].resize((W // 2, H // 2), Image.LANCZOS)
                    canvas = Image.new('RGB', (W, H)); x0, y0 = W // 4, H // 4
                    # the border starts as a blurred, stretched copy of the picture (a far better start than grey)
                    canvas.paste(layers[-1].resize((W, H)).filter(ImageFilter.GaussianBlur(24)), (0, 0)); canvas.paste(small, (x0, y0))
                    mask = Image.new('L', (W, H), 255); m = Image.new('L', (W // 2 - 2 * fe, H // 2 - 2 * fe), 0)
                    mask.paste(m, (x0 + fe, y0 + fe)); mask = mask.filter(ImageFilter.GaussianBlur(fe / 3))
                    out = inp(prompt=full(p), negative_prompt=CFG['negative'], image=canvas, mask_image=mask, width=W, height=H,
                              num_inference_steps=CFG['steps'], guidance_scale=CFG['guidance'], strength=0.99, generator=g).images[0]
                    # put the inner picture back exactly; blend only its outer feather so there is no hard edge
                    a = np.zeros((H // 2, W // 2), np.float32); a[fe:-fe, fe:-fe] = 1
                    a = np.asarray(Image.fromarray((a * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(fe / 3)), np.float32) / 255
                    a[2 * fe:-2 * fe, 2 * fe:-2 * fe] = 1
                    o = np.asarray(out, np.float32); s = np.asarray(small, np.float32)
                    reg = o[y0:y0 + H // 2, x0:x0 + W // 2]; o[y0:y0 + H // 2, x0:x0 + W // 2] = reg * (1 - a[..., None]) + s * a[..., None]
                    img = Image.fromarray(np.clip(o, 0, 255).astype(np.uint8)); img.save(os.path.join(d, '%d.jpg' % k), quality=95); layers.append(img)
                    # the next layer's inner half must equal THIS picture, feather included: from now on it is what it is
                sec = time.time() - t; took.append(sec)
                q.put(('chain', dict(j, ok=True, layers=len(layers), seconds=round(sec), gpu=gpu)))
                log('gpu %d: %s %d layers in %.0fs' % (gpu, j['id'], len(layers), sec))
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache(); q.put(('chain', dict(j, ok=False, error='out of memory', gpu=gpu))); log('gpu %d: OOM on %s' % (gpu, j['id']))
            except Exception:
                q.put(('chain', dict(j, ok=False, error=traceback.format_exc()[-1500:], gpu=gpu))); log('gpu %d: failed %s' % (gpu, j['id']))
        q.put(('done', gpu))
    except Exception:
        q.put(('error', traceback.format_exc())); q.put(('done', gpu))


def main():
    os.makedirs(CH, exist_ok=True)
    n = gpus(); log('gpus:', n)
    if not n: sys.exit('no GPU: Kaggle gave this run none')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-U', 'diffusers==0.43.0', 'accelerate'], check=True)
    from huggingface_hub import snapshot_download
    for mid in (BASE, INPAINT):
        snapshot_download(mid, allow_patterns=['*.json', '*.txt', '*fp16.safetensors', 'tokenizer*/*', '*.model'])
    snapshot_download('madebyollin/sdxl-vae-fp16-fix'); log('weights ready')
    ctx = mp.get_context('spawn'); q = ctx.Queue(); ps = []
    for g in range(n):
        p = ctx.Process(target=worker, args=(g, JOBS[g::n], q)); p.start(); ps.append(p)
    man = dict(batch=CFG['batch'], chains=[], errors=[], gpus=n, model='SDXL base 1.0 + SDXL inpainting 0.1'); done = 0
    while done < n:
        kind, v = q.get()
        if kind == 'chain': man['chains'].append(v)
        elif kind == 'error': man['errors'].append(v); log(v)
        elif kind == 'done': done += 1
        json.dump(man, open(os.path.join(OUT, 'manifest.json'), 'w'), indent=1)
    for p in ps: p.join()
    log('finished: %d chains ok' % sum(1 for c in man['chains'] if c.get('ok')))


if __name__ == '__main__':
    main()
