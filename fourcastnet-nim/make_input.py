import sys
import numpy as np
from datetime import datetime
from earth2studio.data import ARCO
from earth2studio.models.px.sfno import VARIABLES

# Usage: python make_input.py /path/to/fcn_inputs.npy
out_path = sys.argv[1] if len(sys.argv) > 1 else "fcn_inputs.npy"

# Build dataset and save as float32
ds = ARCO()
da = ds(time=datetime(2023, 1, 1), variable=VARIABLES)
np.save(out_path, da.to_numpy()[None].astype("float32"))

print(f"Wrote {out_path}")
