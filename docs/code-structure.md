# TODO

`local_data/`: contain files used only locally. In deployment, these files should be replaced.
    - jwtRS256.key: generated using

```bash
ssh-keygen -t rsa -b 4096 -m PEM -f jwtRS256.key
# Don't add passphrase
openssl rsa -in jwtRS256.key -pubout -outform PEM -out jwtRS256.key.pub
```