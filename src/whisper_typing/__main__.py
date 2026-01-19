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
    parser.add_argument("--hotkey", default="<f8>", help="Global hotkey to toggle recording (e.g., '<f8>')")
    parser.add_argument("--type-hotkey", default="<f9>", help="Global hotkey to type the pending text (e.g., '<f9>')")
    parser.add_argument("--model", default="openai/whisper-base", help="Whisper model ID")
    parser.add_argument("--language", default=None, help="Language code")
    
    args = parser.parse_args()
    
    print(f"Initializing Whisper Typing...")
    print(f"Record Hotkey: {args.hotkey}")
    print(f"Type Hotkey:   {args.type_hotkey}")
    print(f"Model:         {args.model}")
    
    try:
        recorder = AudioRecorder()
        transcriber = Transcriber(model_id=args.model, language=args.language)
        typer = Typer()
    except Exception as e:
        print(f"Error initializing components: {e}")
        return

    is_processing = False
    pending_text = None

    def on_record_toggle():
        nonlocal is_processing, pending_text
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
                    nonlocal is_processing, pending_text
                    try:
                        text = transcriber.transcribe(audio_path)
                        if text:
                            pending_text = text
                            print(f"\n[PREVIEW] Transcribed text: \"{text}\"")
                            print(f"Press {args.type_hotkey} to type this text.")
                        else:
                            print("\n[PREVIEW] No text transcribed.")
                    except Exception as e:
                        print(f"Error during processing: {e}")
                    finally:
                        is_processing = False
                        
                threading.Thread(target=process_audio).start()
            else:
                print("No audio recorded.")
        else:
            # Start recording
            # Clear any pending text when starting a new recording? 
            # Ideally yes, to avoid confusion.
            pending_text = None 
            recorder.start()

    def on_type_confirm():
        nonlocal pending_text
        if pending_text:
            typer.type_text(pending_text)
            pending_text = None # Clear after typing
            print("\nText typed and cleared.")
        else:
            print("\nNo pending text to type. Record something first.")

    print(f"Ready! Press {args.hotkey} to toggle recording.")
    
    try:
        with keyboard.GlobalHotKeys({
            args.hotkey: on_record_toggle,
            args.type_hotkey: on_type_confirm
        }) as h:
            h.join()
    except ValueError as e:
        print(f"Invalid hotkey format. Please use pynput format (e.g., '<f8>', '<ctrl>+<alt>+h')")
        print(f"Error details: {e}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")
