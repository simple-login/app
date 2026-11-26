from abc import ABC, abstractmethod
from typing import List, Optional

import dns.resolver

from app.config import NAMESERVERS

_include_spf = "include:"


class DNSLookupError(Exception):
    """
    The DNS query could not be answered (timeout, SERVFAIL, REFUSED...).

    This is different from the domain not having the requested record (NXDOMAIN / NoAnswer),
    which is a valid answer and is reported as an empty result.
    """

    def __init__(self, hostname: str, rdtype: str, reason: str):
        self.hostname = hostname
        self.rdtype = rdtype
        self.reason = reason
        super().__init__(f"DNS {rdtype} lookup for {hostname} failed: {reason}")


# Exceptions that mean "the query was answered and there are no records"
_EMPTY_ANSWER_EXCEPTIONS = (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer)


def _handle_lookup_exception(
    e: Exception, hostname: str, rdtype: str, raise_on_error: bool
):
    if not raise_on_error or isinstance(e, _EMPTY_ANSWER_EXCEPTIONS):
        return
    reason = str(e) or type(e).__name__
    raise DNSLookupError(hostname, rdtype, f"{type(e).__name__}: {reason}") from e


class DNSClient(ABC):
    @abstractmethod
    def get_cname_record(
        self, hostname: str, raise_on_error: bool = False
    ) -> Optional[str]:
        pass

    @abstractmethod
    def get_a_record(self, hostname: str) -> Optional[str]:
        pass

    @abstractmethod
    def get_mx_domains(
        self, hostname: str, raise_on_error: bool = False
    ) -> dict[int, list[str]]:
        pass

    def get_spf_domain(self, hostname: str, raise_on_error: bool = False) -> List[str]:
        """
        return all domains listed in *include:*
        If raise_on_error is set, DNSLookupError is raised when the DNS query fails
        """
        records = self.get_txt_record(hostname, raise_on_error=raise_on_error)
        try:
            ret = []
            for record in records:
                if record.startswith("v=spf1"):
                    parts = record.split(" ")
                    for part in parts:
                        if part.startswith(_include_spf):
                            ret.append(
                                part[part.find(_include_spf) + len(_include_spf) :]
                            )
            return ret
        except Exception:
            return []

    @abstractmethod
    def get_txt_record(self, hostname: str, raise_on_error: bool = False) -> List[str]:
        """
        If raise_on_error is set, DNSLookupError is raised when the DNS query fails
        instead of returning an empty list.
        """
        pass


class NetworkDNSClient(DNSClient):
    def __init__(self, nameservers: List[str]):
        self._resolver = dns.resolver.Resolver()
        self._resolver.nameservers = nameservers

    def get_cname_record(
        self, hostname: str, raise_on_error: bool = False
    ) -> Optional[str]:
        """
        Return the CNAME record if exists for a domain, WITHOUT the trailing period at the end
        """
        try:
            answers = self._resolver.resolve(hostname, "CNAME", search=True)
            for a in answers:
                ret = a.to_text()
                return ret[:-1]
        except Exception as e:
            _handle_lookup_exception(e, hostname, "CNAME", raise_on_error)
            return None

    def get_a_record(self, hostname: str) -> Optional[str]:
        """
        Return the A RECORD if exists for a domain
        """
        try:
            answers = self._resolver.resolve(hostname, "A", search=True)
            for a in answers:
                ret = a.to_text()
                return ret
        except Exception:
            return None

    def get_mx_domains(
        self, hostname: str, raise_on_error: bool = False
    ) -> dict[int, list[str]]:
        """
        return list of (priority, domain name) sorted by priority (lowest priority first)
        domain name ends with a "." at the end.
        If raise_on_error is set, DNSLookupError is raised when the DNS query fails
        """
        ret = {}
        try:
            answers = self._resolver.resolve(hostname, "MX", search=True)
            for a in answers:
                record = a.to_text()  # for ex '20 alt2.aspmx.l.google.com.'
                parts = record.split(" ")
                prio = int(parts[0])
                if prio not in ret:
                    ret[prio] = []
                ret[prio].append(parts[1])
        except Exception as e:
            _handle_lookup_exception(e, hostname, "MX", raise_on_error)
        return ret

    def get_txt_record(self, hostname: str, raise_on_error: bool = False) -> List[str]:
        try:
            answers = self._resolver.resolve(hostname, "TXT", search=False)
            ret = []
            for a in answers:  # type: dns.rdtypes.ANY.TXT.TXT
                for record in a.strings:
                    ret.append(record.decode())
            return ret
        except Exception as e:
            _handle_lookup_exception(e, hostname, "TXT", raise_on_error)
            return []


class InMemoryDNSClient(DNSClient):
    def __init__(self):
        self.cname_records: dict[str, Optional[str]] = {}
        self.a_records: dict[str, Optional[str]] = {}
        self.mx_records: dict[int, dict[int, list[str]]] = {}
        self.spf_records: dict[str, List[str]] = {}
        self.txt_records: dict[str, List[str]] = {}
        # (hostname, rdtype) -> reason. Simulates a failing DNS query
        self.lookup_errors: dict[tuple[str, str], str] = {}

    def set_lookup_error(self, hostname: str, rdtype: str, reason: str = "Timeout"):
        self.lookup_errors[(hostname, rdtype)] = reason

    def _check_error(self, hostname: str, rdtype: str, raise_on_error: bool) -> bool:
        """Return True if the lookup should be considered failed"""
        reason = self.lookup_errors.get((hostname, rdtype))
        if reason is None:
            return False
        if raise_on_error:
            raise DNSLookupError(hostname, rdtype, reason)
        return True

    def set_cname_record(self, hostname: str, cname: str):
        self.cname_records[hostname] = cname

    def set_a_record(self, hostname: str, a_record: str):
        self.a_records[hostname] = a_record

    def set_mx_records(self, hostname: str, mx_list: dict[int, list[str]]):
        self.mx_records[hostname] = mx_list

    def set_txt_record(self, hostname: str, txt_list: List[str]):
        self.txt_records[hostname] = txt_list

    def get_cname_record(
        self, hostname: str, raise_on_error: bool = False
    ) -> Optional[str]:
        if self._check_error(hostname, "CNAME", raise_on_error):
            return None
        return self.cname_records.get(hostname)

    def get_a_record(self, hostname: str) -> Optional[str]:
        return self.a_records.get(hostname)

    def get_mx_domains(
        self, hostname: str, raise_on_error: bool = False
    ) -> dict[int, list[str]]:
        if self._check_error(hostname, "MX", raise_on_error):
            return {}
        return self.mx_records.get(hostname, {})

    def get_txt_record(self, hostname: str, raise_on_error: bool = False) -> List[str]:
        if self._check_error(hostname, "TXT", raise_on_error):
            return []
        return self.txt_records.get(hostname, [])


global_dns_client: Optional[DNSClient] = None


def get_network_dns_client() -> DNSClient:
    global global_dns_client
    if global_dns_client is not None:
        return global_dns_client
    return NetworkDNSClient(NAMESERVERS)


def set_global_dns_client(dns_client: Optional[DNSClient]):
    global global_dns_client
    global_dns_client = dns_client


def get_mx_domains(hostname: str, raise_on_error: bool = False) -> dict[int, list[str]]:
    return get_network_dns_client().get_mx_domains(
        hostname, raise_on_error=raise_on_error
    )


def get_a_record(hostname: str) -> Optional[str]:
    return get_network_dns_client().get_a_record(hostname)
