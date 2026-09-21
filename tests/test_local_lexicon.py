import json
from speech_tool import lexicon


def test_local_glossary_overrides_public_default(tmp_path, monkeypatch):
    default = tmp_path / 'asr_lexicon.json'
    default.write_text(json.dumps({'entries': [{'intended': 'Generic'}]}))
    monkeypatch.setattr(lexicon, '_LEXICON_PATH', default)
    lexicon.load_lexicon.cache_clear()
    try:
        assert lexicon.load_lexicon()[0]['intended'] == 'Generic'
        default.with_name('asr_lexicon.local.json').write_text(json.dumps({'entries': [{'intended': 'Local override'}]}))
        lexicon.load_lexicon.cache_clear()
        assert lexicon.load_lexicon()[0]['intended'] == 'Local override'
    finally:
        lexicon.load_lexicon.cache_clear()
