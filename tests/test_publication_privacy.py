import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('privacy_check', Path(__file__).parents[1] / 'scripts/privacy-check.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_sensitive_artifacts_and_content_are_rejected():
    for path in ['.env.production', 'raw_transcript.txt', 'events/id/event.json', '.cursorrules', 'docs/asr_lexicon.local.json', 'audio.wav']:
        assert guard.inspect(path, b'example')
    assert guard.inspect('config.py', ('sk-' + 'x' * 30).encode())
    assert guard.inspect('README.md', ('person' + '@' + 'private.test').encode())
    assert guard.inspect('README.md', ('/Users/' + 'someone/private').encode())


def test_generic_code_and_example_identity_pass():
    assert not guard.inspect('src/module.py', b'print("hello")')
    assert not guard.inspect('README.md', b'developer@example.com')
    assert not guard.inspect('README.md', b'123+example@users.noreply.github.com')
