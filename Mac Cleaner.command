#!/bin/bash
# Double-click in Finder to open the dashboard.
cd "$(dirname "$0")" && exec /usr/bin/env python3 -m macclean serve
