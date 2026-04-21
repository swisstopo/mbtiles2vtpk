import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mbtiles2vtpk.cli import main

sys.exit(main())
