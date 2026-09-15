import uvicorn
import gradio as gr
from app.main import app as fastapi_app

# Hugging Face Gradio Spaces require a valid Gradio app at the root (/) to pass health checks.
# We create a simple dummy Gradio interface and mount it onto our FastAPI app.
demo = gr.Interface(
    fn=lambda: "CANOPY API is running successfully!",
    inputs=None,
    outputs="text",
    title="CANOPY API"
)

app = gr.mount_gradio_app(fastapi_app, demo, path="/")
# Hugging Face will automatically find the `app` variable and serve it on port 7860.
# We do not need to call uvicorn.run() manually.
