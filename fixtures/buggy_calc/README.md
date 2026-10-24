# buggy_calc fixture

A deliberately broken target for Lumen's coding-task mode: `add` subtracts, so
`test_add` fails while `test_sub` passes. Copy this directory somewhere
writable and point Lumen at the copy:

```bash
cp -r fixtures/buggy_calc /tmp/lumen-target
python3 lumen.py --task coding --target /tmp/lumen-target
```

Do not point Lumen at the fixture in place unless you want it fixed in your
working tree.
