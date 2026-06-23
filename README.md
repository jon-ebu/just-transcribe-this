this is a transcription app i made to help transcribe voicemail.wav files but could be useful for other stuff too maybe
it runs locally using the openai whisper ai https://github.com/openai/whisper

To strip the macOS quarantine flag so the app opens without Gatekeeper
  blocking it:

  xattr -cr "/Applications/Just Transcribe This.app"

  - -c clears all extended attributes
  - -r recurses into the bundle

  Or if you're working with the DMG before installing:

  xattr -c "Just Transcribe This.dmg"   

100% vibecoded

hope you enjoy!
