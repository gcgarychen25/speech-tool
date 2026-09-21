# Meeting audio and truthful recovery status

Preserve the existing restrained interface and all source recordings. Distinguish
upload gaps, ASR failures, and optional cleanup failures. Never imply that saved
raw transcription was lost because cleanup failed.

Meeting capture is explicit: choose Meeting audio + microphone, click Record,
select a meeting tab and enable sharing its audio. Remember the source preference.
The shortcut opens a ready screen in meeting mode; browser permission cannot be
bypassed. Microphone/classroom mode retains shortcut auto-start. A Web Audio mix
feeds an audio-only MediaRecorder. Shared video is never recorded or uploaded.
Separate meters show actual signal. Missing audio and cancelled permission are
visible errors; no silent microphone-only fallback. Ending sharing stops capture.

Platform boundary: system/window audio availability depends on browser and OS.
Use a meeting's browser tab when its native app cannot share audio. No virtual
audio driver or native screen-capture helper is installed by this change.

Verification: synthetic Chrome tests cover lost acknowledgement, offline reload,
partial/manual recovery, index gaps, conflicts, notes preservation, meeting mix,
permission cancellation, missing shared audio, and sharing-ended stop. Backend
suite: 66 tests. Actual meeting-source permission and remote speaker audibility
still require a user test; synthetic signals are not proof of OS capture support.

A UI/status patch cannot recover a missing upload by itself. Check Recover audio
in the original browser. All stored raw text remains intact.
