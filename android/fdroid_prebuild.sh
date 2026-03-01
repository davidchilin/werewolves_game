#!/bin/bash
cd app
mkdir -p python_wheels

# Note: We are specifically using pip3.10 here!
pip3 download -d python_wheels flask flask-socketio python-dotenv
pip3 download --no-binary markupsafe markupsafe

mkdir markupsafe_src
tar -xzf markupsafe-*.tar.gz -C markupsafe_src --strip-components=1

rm -f markupsafe_src/src/markupsafe/_speedups.c
pip3 wheel ./markupsafe_src --no-deps -w python_wheels

rm -rf markupsafe_src markupsafe-*.tar.gz

