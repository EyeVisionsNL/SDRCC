# SDRCC documentation website

Published from the dedicated `gh-pages` branch, root folder. Application branches are independent.

The source Markdown is in `source/`; `build.py` renders all eight pages, shared navigation and search data. Artwork and screenshots use existing SDRCC assets pinned to the stable source commit. Change that asset ref deliberately when updating screenshots.

To edit: update Markdown, CSS or JavaScript, install `requirements.txt`, then run `python build.py`. Commit both source and generated HTML/search.json to this branch. GitHub Pages publishes the root without Jekyll.

The original GitHub Wiki remains available. This website uses a snapshot of its guides, so wiki edits must be copied to `source/` and rebuilt; they are not automatically synchronized.
