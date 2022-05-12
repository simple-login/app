from monitoring import _process_ps_output


def test_monitoring_proc_count():
    data = """
    PID TTY      STAT   TIME COMMAND
   1432 ?        S<     0:00 [loop44]
   3438 ?        Ssl    0:00 /bin/sh arg
   3440 ?        Sl     0:00 /bin/cron args
   3440 ?        Sl     0:00 smtp arg
   3448 ?        Sl     0:00 smtpd arg
   3441 ?        Sl     0:00 other smtpd arg
    """
    result = _process_ps_output(["smtp", "smtpd", "cron"], data)
    assert 1 == result["smtp"]
    assert 1 == result["smtpd"]
    assert 0 == result["cron"]
