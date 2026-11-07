#!/bin/zsh
cd "${0:A:h}/.."
python3 -m app.server --preview
