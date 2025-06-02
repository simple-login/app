# Troubleshooting

## A. If you can't receive a welcome email when signing up

This can either mean:

1) Postfix can't send emails to your mailbox
2) The `sl-app` container can't connect to Postfix (run on the host)

### A.1
To test 1), running `swaks --to your-mailbox@mail.com` should send you an email.
Make sure to replace `your-mailbox@mail.com` by your mailbox address.
`swaks` can be installed with `sudo apt install swaks` on Debian-based OS.

### A.2
Once 1) works, we can test the 2) by

a) first connecting to the container by `docker exec -it sl-app bash`
b) then run the following commands

```bash
apt update
apt install telnet -y
telnet 10.0.0.1 25
```

If the `telnet 10.0.0.1 25` doesn't work, it means Postfix can't be reached from the docker container.
This means an issue with the Docker network.

You can then try `telnet 172.17.0.1 25` as `172.17.0.1` is *usually* the host IP address. If this works, then you can set
the `POSTFIX_SERVER=172.17.0.1` in your SimpleLogin config file `~/simplelogin.env` and re-run all the containers.

If not, please run through the self-hosting instructions and make sure no step is missed.

## B. You send an email to your alias and can't receive the forwarded email on your mailbox

This can be either due to:

1) Postfix doesn't recognize the alias domain
2) Postfix can't connect to the `sl-email` container
3) `sl-email` container can't connect to Postfix
4) Postfix can't send emails to

### B.1
For 1), this can mean the `/etc/postfix/pgsql-relay-domains.cf` and `/etc/postfix/pgsql-transport-maps.cf` aren't correctly set up.
To test 1), `postmap -q mydomain.com pgsql:/etc/postfix/pgsql-relay-domains.cf` should return `mydomain.com`.

And `postmap -q not-exist.com pgsql:/etc/postfix/pgsql-relay-domains.cf` should return nothing.

`postmap -q mydomain.com pgsql:/etc/postfix/pgsql-transport-maps.cf` should return `smtp:127.0.0.1:20381`

And `postmap -q not-exist.com pgsql:/etc/postfix/pgsql-transport-maps.cf` should return nothing.

### B.2
For 2), you can check in the `sl-email` log by running `docker logs sl-email` and if the incoming email doesn't appear there,
then it means Postfix can't connect to the `sl-email` container. Please run through the self-hosting instructions and
make sure no step is missed.

### B.3

For 3), you can check in the `sl-email` log by running `docker logs sl-email` and make sure there's no error there.

### B.4
For 4), please refer to the A.1 section to make sure Postfix can send emails to your mailbox.

