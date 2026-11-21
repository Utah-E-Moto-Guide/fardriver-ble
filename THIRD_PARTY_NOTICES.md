# Third-party notices

## jackhumbert/fardriver-controllers (MIT)

`fardriver_ble/decode.py` uses the frame-id-to-address table (`FLASH_READ_ADDR`) published in
https://github.com/jackhumbert/fardriver-controllers. Several field names in
`fardriver_ble/address_map.py` for blocks the official app never displays (0xA0 command register,
0xAC..0xB1 binding store, 0x0B bit layout, 0xF4..0xF9 runtime words) come from that project's notes,
rewritten in our own words. The factory-reset frame used as a test vector in `tests/test_nudge.py`
is documented there.

MIT License

Copyright (c) 2024 Jack Humbert

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Facts from other sources (no code or text copied)

- Official Fardriver Android app 288 (Nanjing FarDriver): protocol behaviour, field meanings, limits and
  fault names were learned by reading a local decompile. No code, strings or binaries are in this repo
  (see `.gitignore`: `local/`, `*.apk`, `*.dll`).
- Fardriver "adjustment instructions of the control parameters" PDF (far-driver.com): tuning guidance
  paraphrased with attribution in `knowledge/settings.yml`. The PDF is not in this repo.
- MAXAPACITY "DRAX Apex FarDriver tuning guide": credited for how to tune this particular bike
  (stock settings, owner results, safety practice). Community claims paraphrased with attribution in
  `knowledge/settings.yml`, with a few short quoted phrases. Individual owners are not named.
- GDriver XLSX labels: used to cross-check field names; the owner's export file is not in this repo.
