import numpy as np
import requests
from datetime import datetime
from earth2studio.data import ARCO
from earth2studio.models.px.sfno import VARIABLES


def main():
    """Generate an input array and send it to a local FourCastNet NIM."""
    ds = ARCO()
    da = ds(time=datetime(2023, 1, 1), variable=VARIABLES)
    input_array = da.to_numpy()[None].astype("float32")
    np.save("fcn_inputs.npy", input_array)

    resp = requests.get(
        "http://localhost:8000/v1/health/ready",
        headers={"accept": "application/json"},
    )
    resp.raise_for_status()

    files = {
        "input_array": open("fcn_inputs.npy", "rb"),
        "input_time": (None, "2023-01-01T00:00:00Z"),
        "simulation_length": (None, "4"),
    }
    resp = requests.post("http://localhost:8000/v1/infer", files=files)
    resp.raise_for_status()

    with open("output.tar", "wb") as f:
        f.write(resp.content)
    print("Output saved to output.tar")


if __name__ == "__main__":
    main()
