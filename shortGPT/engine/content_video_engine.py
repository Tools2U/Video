import gradio as gr
import logging
import os
from shortGPT.engine.content_video_engine import ContentVideoEngine
from shortGPT.audio.voice_module import VoiceModule
from shortGPT.config.languages import Language

class VideoAutomationUI:
    def __init__(self):
        # Initialize necessary variables and components
        self.script = ""
        self.voice_module = VoiceModule()
        self.isVertical = False
        self.language = Language.ENGLISH
        self.progress = None  # Placeholder for progress tracking
        # Set up logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def make_video(self, script, voice_module, is_vertical, progress=None):
        """
        Function to generate the video using ContentVideoEngine.
        """
        try:
            video_engine = ContentVideoEngine(
                voiceModule=voice_module,
                script=script,
                isVerticalFormat=is_vertical,
                language=self.language
            )

            # Iterate through the content creation steps
            for step_num, step_info in video_engine.makeContent():
                if progress:
                    progress((step_num + 1) / len(video_engine.stepDict), f"Executing step {step_num + 1}: {step_info}")
                self.logger.info(f"Completed step {step_num + 1}: {step_info}")

            # After content creation, retrieve the video path
            video_path = video_engine._db_video_path
            return video_path

        except Exception as e:
            self.logger.error(f"Error during video generation: {str(e)}")
            raise e

    def respond(self, user_input, chatbot_history, is_vertical, progress=gr.Progress()):
        """
        Gradio event handler for user interactions.
        """
        # Update internal state based on user input
        self.script = user_input
        self.isVertical = is_vertical

        # Provide initial feedback to the user
        chatbot_history.append((user_input, "Processing your request..."))
        yield (
            gr.Textbox.update(value=""),
            gr.Chatbot.update(value=chatbot_history),
            gr.HTML.update(value=""),
            gr.HTML.update(value=""),
            gr.Button.update(visible=False),
            gr.Button.update(visible=False),
        )

        try:
            # Generate the video
            video_path = self.make_video(self.script, self.voice_module, self.isVertical, progress=progress)

            # Provide download link and success message
            if os.path.exists(video_path):
                video_filename = os.path.basename(video_path)
                download_link = f"<a href='file/{video_filename}' download>Download Your Video</a>"
                chatbot_history.append((None, "Your video is ready! 🎉"))
                yield (
                    gr.Textbox.update(visible=False),
                    gr.Chatbot.update(value=chatbot_history),
                    gr.HTML.update(value=download_link, visible=True),
                    gr.HTML.update(value="", visible=False),
                    gr.Button.update(visible=True),
                    gr.Button.update(visible=True),
                )
            else:
                # Handle the case where video_path does not exist
                chatbot_history.append((None, "An error occurred: Video file not found."))
                yield (
                    gr.Textbox.update(visible=False),
                    gr.Chatbot.update(value=chatbot_history),
                    gr.HTML.update(visible=False),
                    gr.HTML.update(visible=False),
                    gr.Button.update(visible=True),
                    gr.Button.update(visible=True),
                )

        except Exception as e:
            # Handle exceptions and provide error feedback
            error_message = f"An error occurred during video generation: {str(e)}"
            self.logger.error(error_message)
            chatbot_history.append((None, error_message))
            yield (
                gr.Textbox.update(visible=False),
                gr.Chatbot.update(value=chatbot_history),
                gr.HTML.update(visible=False),
                gr.HTML.update(visible=False),
                gr.Button.update(visible=True),
                gr.Button.update(visible=True),
            )

    def launch_interface(self):
        """
        Function to set up and launch the Gradio interface.
        """
        with gr.Blocks() as demo:
            gr.Markdown("# 🎬 Video Automation Interface")

            with gr.Row():
                user_input = gr.Textbox(
                    label="Enter your script",
                    placeholder="Type your script here...",
                    lines=5
                )
                is_vertical = gr.Checkbox(
                    label="Vertical Video Format",
                    value=False
                )

            chatbot = gr.Chatbot()

            with gr.Row():
                submit_btn = gr.Button("Generate Video")
                clear_btn = gr.Button("Clear Chat")

            download_link = gr.HTML(visible=False)
            error_message = gr.HTML(visible=False)

            # Set up event handlers
            submit_btn.click(
                self.respond,
                inputs=[user_input, chatbot, is_vertical],
                outputs=[user_input, chatbot, download_link, error_message, submit_btn, clear_btn],
            )

            clear_btn.click(
                lambda: (
                    gr.Textbox.update(value=""),
                    gr.Chatbot.update(value=[]),
                    gr.HTML.update(value="", visible=False),
                    gr.HTML.update(value="", visible=False),
                    gr.Button.update(visible=True),
                    gr.Button.update(visible=True),
                ),
                outputs=[user_input, chatbot, download_link, error_message, submit_btn, clear_btn],
            )

        demo.launch()

# Initialize and launch the interface
if __name__ == "__main__":
    video_ui = VideoAutomationUI()
    video_ui.launch_interface()
