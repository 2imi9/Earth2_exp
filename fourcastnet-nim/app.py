import gradio as gr
from vllm import LLM, SamplingParams
import point_stats

# Lazy globals for dataset and model
_DS = None
_LLM = None
_SAMPLING = SamplingParams(temperature=0.7, max_tokens=200)


def _ensure_resources():
    """Load forecast dataset and language model once."""
    global _DS, _LLM
    if _DS is None:
        try:
            _DS = point_stats._load_dataset()
        except Exception as e:  # pragma: no cover
            _DS = e
    if _LLM is None:
        try:
            _LLM = LLM(model="gpt-oss-20b")
        except Exception as e:  # pragma: no cover
            _LLM = e


_ensure_resources()


def answer(lat, lon, question, when, interp):
    """Generate a response about the environment at a location."""
    if isinstance(_DS, Exception):
        return f"Dataset load failed: {_DS}"
    if isinstance(_LLM, Exception):
        return f"Model load failed: {_LLM}"

    when = when.strip() or None
    if when:
        df = point_stats.point_at_time(float(lat), float(lon), when, interp=interp, ds=_DS)
    else:
        df = point_stats.point_timeseries(float(lat), float(lon), ds=_DS)

    stats = df.to_csv(index=False)
    prompt = (
        f"You are a helpful environmental assistant. Given the following forecast data for "
        f"latitude {lat} and longitude {lon} from FourCastNet:\n{stats}\n"
        f"Answer the user's question: {question}"
    )
    outputs = _LLM.generate([prompt], _SAMPLING)
    return outputs[0].outputs[0].text.strip()


with gr.Blocks() as demo:
    gr.Markdown("# Environment Q&A")
    with gr.Row():
        lat = gr.Number(label="Latitude", value=0.0)
        lon = gr.Number(label="Longitude", value=0.0)
    when = gr.Textbox(label="Time (ISO8601, optional)")
    interp = gr.Dropdown(["nearest", "linear"], value="nearest", label="Interpolation")
    q = gr.Textbox(label="Question")
    ans = gr.Textbox(label="Answer")
    btn = gr.Button("Ask")
    btn.click(answer, inputs=[lat, lon, q, when, interp], outputs=ans)


if __name__ == "__main__":  # pragma: no cover
    demo.launch()
