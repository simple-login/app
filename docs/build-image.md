To build a multi-architecture image, you need to use `buildx`.

Here's the command to build and push the images from a Mac M1:

1) First create a new buildx environment (or context). This is only necessary for the first time.

```bash
docker buildx create --use
```

2) Build and push the image. Replace `simplelogin/name:tag` by the correct docker image name and tag.

```bash
docker buildx build --platform linux/amd64,linux/arm64 --push -t simplelogin/name:tag
```