const MAX_BYTES = 10240; // 10KiB

function enableDragDropForPGPKeys(inputID) {
    function drop(event) {
        event.stopPropagation();
        event.preventDefault();

        let files = event.dataTransfer.files;
        for (let i = 0; i < files.length; i++) {
            let file = files[i];
            const isValidPgpFile = file.type === 'text/plain' || file.name.endsWith('.asc') || file.name.endsWith('.pub') || file.name.endsWith('.pgp') || file.name.endsWith('.key');
            if (!isValidPgpFile) {
                toastr.warning(`File ${file.name} is not a public key file`);
                continue;
            }
            let reader = new FileReader();
            reader.onloadend = onFileLoaded;
            reader.readAsBinaryString(file);
        }
        dropArea.classList.remove("dashed-outline");
    }

    function onFileLoaded(event) {
        const initialData = event.currentTarget.result.substr(0, MAX_BYTES);
        $(inputID).val(initialData);
    }

    const dropArea = $(inputID).get(0);
    dropArea.addEventListener("dragenter", (event) => {
        event.stopPropagation();
        event.preventDefault();
        dropArea.classList.add("dashed-outline");
    });
    dropArea.addEventListener("dragover", (event) => {
        event.stopPropagation();
        event.preventDefault();
        dropArea.classList.add("dashed-outline");
    });
    dropArea.addEventListener("dragleave", (event) => {
        event.stopPropagation();
        event.preventDefault();
        dropArea.classList.remove("dashed-outline");
    });
    dropArea.addEventListener("drop", drop, false);
}
