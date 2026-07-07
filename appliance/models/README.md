# Real model assets for the shipped appliance

These are the actual weights the packaged appliance runs — not the
synthetic test fixture at `userland/init/fixtures/` (that one is
deliberately fake data used only by the automated verify scripts, which
assert byte-exact determinism rather than language quality; see REPORT.md's
"Known Limitation" history for why the two must stay separate).

- `stories15M-q8.bin` — Karpathy's TinyStories-15M checkpoint
  (`karpathy/tinyllamas` on Hugging Face), converted from the original
  legacy fp32 `.bin` format into the v2 int8-quantized format
  `userland/heliox-daemon/src/cognitive/inference.rs` actually parses,
  using `scripts/convert_model_v2.py`. **Group size 32, not 64** — this
  model's `dim=288` isn't evenly divisible by 64 (`288 / 64 = 4.5`), and
  the inference engine's per-group quantization silently drops the
  trailing partial group on every matmul if group size doesn't divide
  `dim` and `hidden_dim` cleanly (see REPORT.md's Phase D4 section for the
  full story - this exact mismatch was shipped once and produced
  `<unk><unk>` instead of real text). Standard-tier model.
- `tokenizer.bin` — the matching 32000-token SentencePiece tokenizer from
  `karpathy/llama2.c`, shared across all TinyStories checkpoint sizes.

## Regenerating or upgrading (e.g. to the High-tier 1.1B model)

```bash
# 1. Fetch the source legacy-format checkpoint (fp32) and tokenizer.
curl -L -o stories15M.bin https://huggingface.co/karpathy/tinyllamas/resolve/main/stories15M.bin
curl -L -o tokenizer.bin https://github.com/karpathy/llama2.c/raw/master/tokenizer.bin

# 2. Quantize to the v2 format (pure numpy, no PyTorch needed - the legacy
#    .bin is just a flat sequence of float32 arrays after a small header).
#    Group size MUST evenly divide both dim and hidden_dim - check with
#    e.g. `python -c "import math; print(math.gcd(dim, hidden_dim))"` and
#    pick a divisor of that gcd. For stories15M (dim=288, hidden_dim=768)
#    that's 32, not the more common default of 64.
python scripts/convert_model_v2.py stories15M.bin stories15M-q8.bin 32
```

The output file size must exactly equal the `total_file_size` the kernel
parser computes from the header fields (256-byte header + the sum of every
tensor's quantized-plus-scale size) - a mismatch here means the config
values in step 1 don't match the source checkpoint's actual architecture.
`scripts/convert_model_v2.py` prints each tensor it writes so a size
mismatch is easy to bisect. A file of the *correct* size can still produce
garbage output if the group size doesn't divide the model's dimensions
evenly - that failure is silent (no error, no size mismatch), so verify
actual generated text quality with `scripts/verify_real_model.mjs`, not
just the file size, after converting a new model.

The same script works for the High-tier `stories1.1B` checkpoint referenced
in `inference.rs`'s `HIGH_TIER_MODEL_PATH` - that one just doesn't ship in
this repo yet (a ~4.4 GB fp32 source download and correspondingly large
quantized output), so the High tier still falls back to the Standard-tier
model on real hardware until that's done.
