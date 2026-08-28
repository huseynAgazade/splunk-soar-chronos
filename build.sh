#!/bin/sh
# Package the app for Apps -> Install App.
set -e
rm -f Chronos.tgz
tar --exclude='__pycache__' -czf Chronos.tgz phChronos/
echo "built Chronos.tgz"
