SimpleLogin needs to have the following ports open:
- 22: so you SSH into the server
- 25: to receive the incoming emails
- 80 and optionally 443 for SimpleLogin webapp

If you use `UFW` Firewall, you could run the following commands to open these ports:

```bash
sudo ufw allow 22
sudo ufw allow 25
sudo ufw allow 80

# optional, enable 443 if you set up TLS for the webapp
sudo ufw allow 443
```

