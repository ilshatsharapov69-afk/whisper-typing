import argparse
import sys
import threading
from pynput import keyboard
from .audio_capture import AudioRecorder
from .transcriber import Transcriber
from .typer import Typer

def main() -> None:
    """Run the application."""
    parser = argparse.ArgumentParser(description="Whisper Typing - Background Speech to Text")
    parser.add_argument("--hotkey", default="<f8>", help="Global hotkey to toggle recording (e.g., '<f8>', '<ctrl>+<alt>+r')")
    parser.add_argument("--model", default="openai/whisper-base", help="Whisper model ID (e.g., 'openai/whisper-large-v3')")
    parser.add_argument("--language", default=None, help="Language code (e.g., 'en', 'fr')")
    
    args = parser.parse_args()
    
    print(f"Initializing Whisper Typing...")
    print(f"Hotkey: {args.hotkey}")
    print(f"Model: {args.model}")
    
    try:
        recorder = AudioRecorder()
        transcriber = Transcriber(model_id=args.model, language=args.language)
        typer = Typer()
    except Exception as e:
        print(f"Error initializing components: {e}")
        return

    is_processing = False

    def on_activate():
        nonlocal is_processing
        if is_processing:
            print("Still processing previous audio, please wait.")
            return

        if recorder.recording:
            # Stop recording and process
            print("\nStopping recording...")
            audio_path = recorder.stop()
            
            if audio_path:
                is_processing = True
                
                def process_audio():
                    nonlocal is_processing
                    try:
                        text = transcriber.transcribe(audio_path)
                        typer.type_text(text)
                    except Exception as e:
                        print(f"Error during processing: {e}")
                    finally:
                        is_processing = False
                        
                threading.Thread(target=process_audio).start()
            else:
                print("No audio recorded.")
        else:
            # Start recording
            recorder.start()

    print(f"Ready! Press {args.hotkey} to start/stop recording.")
    
    # Setup hotkey listener
    # Note: pynput hotkey format is strict. 
    # Single keys: '<f8>'
    # Combos: '<ctrl>+<alt>+h'
    try:
        with keyboard.GlobalHotKeys({
            args.hotkey: on_activate
        }) as h:
            h.join()
    except ValueError as e:
        print(f"Invalid hotkey format '{args.hotkey}'. Please use pynput format (e.g., '<f8>', '<ctrl>+<alt>+h')")
        print(f"Error details: {e}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")
