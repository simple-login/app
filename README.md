# Run the code locally
        
To run the code locally, please create a local setting file based on `.env.example`: 

```
cp .env.example .env
```

Feel free to custom your `.env` file, it would be your default setting when developing locally. This file is ignored by git.

You don't need all the parameters, for ex if you don't update images to s3, then 
`BUCKET`, `AWS_ACCESS_KEY_ID` can be empty or if you don't use login with Github locally, `GITHUB_CLIENT_ID` doesn't have to be filled. The `.env.example` file contains minimal requirement so that if you run:

```
python3 server.py
```

then open http://localhost:7777, you should be able to login with the following account

```
john@wick.com / password
```

# Other topics

Please go to the following pages for different topics:

- [api](docs/api.md)
- [database migration](docs/db-migration.md)
- [oauth](docs/oauth.md) 





