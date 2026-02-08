The Spamhaus Project maintains a reliable list of IP addresses known to be the source of SPAM.
You can check whether a given IP address is in that list by submitting queries to the DNS infrastructure.

Since Spamhaus blocks queries coming from public (open) DNS-Resolvers
(see: <https://check.spamhaus.org/returnc/pub>)
and your VPS running Postfix may use a public resolver by default,
it is recommended to sign up for the free
[Spamhaus Data Query Service](https://www.spamhaus.com/free-trial/sign-up-for-a-free-data-query-service-account/)
and obtain a Spamhaus DQS key.

## Using Spamhaus public mirrors

This project shows configuration for self-hosting that targets the Spamhaus Project public mirror infrastructure. Unfortunately, this fails if the DNS query comes from an open resolver.

```cf
smtpd_recipient_restrictions =
  [...]
  reject_rbl_client zen.spamhaus.org=127.0.0.[2..11],
  reject_rhsbl_sender dbl.spamhaus.org=127.0.1.[2..99],
  reject_rhsbl_helo dbl.spamhaus.org=127.0.1.[2..99],
  reject_rhsbl_reverse_client dbl.spamhaus.org=127.0.1.[2..99],
  warn_if_reject reject_rbl_client zen.spamhaus.org=127.255.255.[1..255],
  permit
```

This manifests itself with the following error message from Postfix:

> NOQUEUE: reject: RCPT from [redacted]: 554 5.7.1 Service unavailable; Client host [redacted] blocked using zen.spamhaus.org; Error: open resolver; <https://check.spamhaus.org/returnc/pub/xxx.xxx.xxx.xxx/>

If you do encounter this error, you may want to register for a free key to the Data Query Service (DQS) as explained in the next section.

## Using Spamhaus Data Query Service

Registering for a free DQS key lets you use the Spamhaus Project Data Query Service
(distinct from the public mirror infrastructure).

Create the `/etc/postfix/dnsbl-reply-map.cf` with the following contents:

```cf
your_DQS_key.zen.dq.spamhaus.net=127.0.0.[2..11]        554 $rbl_class $rbl_what blocked using ZEN - see https://www.spamhaus.org/query/ip/$client_address for details
your_DQS_key.dbl.dq.spamhaus.net=127.0.1.[2..99]        554 $rbl_class $rbl_what blocked using DBL - see $rbl_txt for details
your_DQS_key.zrd.dq.spamhaus.net=127.0.2.[2..24]        554 $rbl_class $rbl_what blocked using ZRD - domain too young
your_DQS_key.zen.dq.spamhaus.net                        554 $rbl_class $rbl_what blocked using ZEN - see https://www.spamhaus.org/query/ip/$client_address for details
your_DQS_key.dbl.dq.spamhaus.net                        554 $rbl_class $rbl_what blocked using DBL - see $rbl_txt for details
your_DQS_key.zrd.dq.spamhaus.net                        554 $rbl_class $rbl_what blocked using ZRD - domain too young
```

Where `your_DSQ_key` is a placeholder for your real DQS key wich looks like a sequence of random numbers and letters.

**Important**: run the Postfix lookup table management `postmap` utility to prepare
the DSNBL reply map:

```sh
postmap /etc/postfix/dnsbl-reply-map
```

Update Postfix configuration to reject messages coming from blocked domains:

```patch
  relay_domains = pgsql:/etc/postfix/pgsql-relay-domains.cf
  transport_maps = pgsql:/etc/postfix/pgsql-transport-maps.cf

+ rbl_reply_maps = lmdb:/etc/postfix/dnsbl-reply-map

  ...

  # Recipient restrictions:
  smtpd_recipient_restrictions =
    reject_unauth_pipelining,
    …
-   reject_rbl_client zen.spamhaus.org=127.0.0.[2..11],
-   reject_rhsbl_sender dbl.spamhaus.org=127.0.1.[2..99],
-   reject_rhsbl_helo dbl.spamhaus.org=127.0.1.[2..99],
-   reject_rhsbl_reverse_client dbl.spamhaus.org=127.0.1.[2..99],
-   warn_if_reject reject_rbl_client zen.spamhaus.org=127.255.255.[1..255],
+   reject_rbl_client your_DQS_key.zen.dq.spamhaus.net=127.0.0.[2..11],
+   reject_rhsbl_sender your_DQS_key.dbl.dq.spamhaus.net=127.0.1.[2..99],
+   reject_rhsbl_helo your_DQS_key.dbl.dq.spamhaus.net=127.0.1.[2..99],
+   reject_rhsbl_reverse_client your_DQS_key.dbl.dq.spamhaus.net=127.0.1.[2..99],
+   reject_rhsbl_sender your_DQS_key.zrd.dq.spamhaus.net=127.0.2.[2..24],
+   reject_rhsbl_helo your_DQS_key.zrd.dq.spamhaus.net=127.0.2.[2..24],
+   reject_rhsbl_reverse_client your_DQS_key.zrd.dq.spamhaus.net=127.0.2.[2..24],
    reject_rbl_client bl.spamcop.net,
    permit
```

Restart Postfix for this change to take effect.

```sh
postfix reload
```
