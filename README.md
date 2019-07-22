
## OAuth flow

Authorization code flow: 

http://sl-server:7777/oauth/authorize?client_id=client-id&state=123456&response_type=code&redirect_uri=http%3A%2F%2Fsl-client%3A7000%2Fcallback&state=dvoQ6Jtv0PV68tBUgUMM035oFiZw57

Implicit flow:
http://sl-server:7777/oauth/authorize?client_id=client-id&state=123456&response_type=token&redirect_uri=http%3A%2F%2Fsl-client%3A7000%2Fcallback&state=dvoQ6Jtv0PV68tBUgUMM035oFiZw57

Exchange the code to get the token with `{code}` replaced by the code obtained in previous step.

http -f -a client-id:client-secret http://localhost:7777/oauth/token grant_type=authorization_code code={code}

Get user info:

http http://localhost:7777/oauth/user_info 'Authorization:Bearer {token}'


## Template structure

base
    single: for login, register page
    default: for all pages when user log ins
        
## How to create new migration

Whenever the model changes, a new migration needs to be created

Set the database connection to use staging environment:

> ln -sf ~/config/simplelogin/staging.env .env

Generate the migration script and make sure to review it:

> flask db migrate

## Code structure

local_data/: contain files used only locally. In deployment, these files should be replaced.
    - jwtRS256.key: generated using 
    
```bash
ssh-keygen -t rsa -b 4096 -m PEM -f jwtRS256.key
# Don't add passphrase
openssl rsa -in jwtRS256.key -pubout -outform PEM -out jwtRS256.key.pub
```

## OpenID, OAuth2 response_type & scope

According to https://medium.com/@darutk/diagrams-of-all-the-openid-connect-flows-6968e3990660

- `response_type` can be either `code, token, id_token`  or any combination.
- `scope` can contain `openid` or not

Below is the different combinations that are taken into account until now:

response_type=code
    scope:
	    with `openid` in scope, return `id_token` at /token: OK
	    without: OK

response_type=token
    scope:
	    with and without `openid`, nothing to do: OK

response_type=id_token
    return `id_token` in /authorization endpoint
    
response_type=id_token token
    return `id_token` in addition to `access_token` in /authorization endpoint
   
response_type=id_token code
    return `id_token` in addition to `authorization_code` in /authorization endpoint
   

# Plan Upgrade, downgrade flow

Here's an example:

July 2019: user takes yearly plan, valid until July 2020
    user.plan=yearly, user.plan_expiration=None
    set user.stripe card-token, customer-id, subscription-id

December 2019: user cancels his plan.
	set plan_expiration to "period end of subscription", ie July 2020
	call stripe:
		stripe.Subscription.modify(
		  user.stripe_subscription_id,
		  cancel_at_period_end=True
		)

There are 2 possible scenarios at this point:
1) user decides to renew on March 2020: 
	set plan_expiration = None
	stripe.Subscription.modify(
	  user.stripe_subscription_id,
	  cancel_at_period_end=False
	)

2) the plan ends on July 2020. 
The cronjob set 
- user stripe_subscription_id , stripe_card_token, stripe_customer_id to None
- user.plan=free, user.plan_expiration=None
- delete customer on stripe

user decides to take the premium plan again: go through all normal flow



