## Updating

Rows live in `data/announcements.yaml`; this README and `docs/index.html` are generated from it.

```
pip install -r requirements.txt
python scripts/preview.py
python scripts/check.py
python scripts/render.py
```

`preview.py` serves the page on localhost and renders it again on every refresh, without writing a file. `check.py` validates every row, checks that each link answers 200 and that the prose has no dashes or filler words. `render.py` rebuilds this README and the filterable page in `docs/`.

Licence: MIT, see `LICENSE`.
