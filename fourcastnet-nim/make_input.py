import sys
from pathlib import Path
import numpy as np
from datetime import datetime
from earth2studio.data import ARCO
from earth2studio.models.px.sfno import VARIABLES

out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fcn_inputs.npy")
out_path.parent.mkdir(parents=True, exist_ok=True)

ds = ARCO()
da = ds(time=datetime(2023, 1, 1), variable=VARIABLES)
np.save(out_path, da.to_numpy()[None].astype("float32"))
