import dns.resolver


def get_mx_domains(hostname) -> [str]:
    answers = dns.resolver.query(hostname, "MX")
    ret = []

    for a in answers:
        record = a.to_text()  # for ex '20 alt2.aspmx.l.google.com.'
        r = record.split(" ")[1]  # alt2.aspmx.l.google.com.
        ret.append(r)

    return ret
