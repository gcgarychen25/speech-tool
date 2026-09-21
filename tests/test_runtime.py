from speech_tool.runtime import pid_alive, pids_listening


def test_pid_alive_self_is_false():
    import os

    assert pid_alive(os.getpid()) is False
    assert pid_alive(0) is False


def test_pids_listening_invalid_port():
    assert pids_listening(1) == [] or all(isinstance(p, int) for p in pids_listening(1))
