const MAX_BYTES = 10240; // 10KiB

function enableDragDropForPGPKeys(inputID) {
    function drop(event) {
        event.stopPropagation();
        event.preventDefault();

        let files = event.dataTransfer.files;
        for (let i = 0; i < files.length; i++) {
            let file = files[i];
            if(file.type !== 'text/plain'){
                toastr.warning(`File ${file.name} is not a public key file`);
                continue;
            }
            let reader = new FileReader();
            reader.onloadend = onFileLoaded;
            reader.readAsBinaryString(file);
        }
    }

    function onFileLoaded(event) {
        const initialData = event.currentTarget.result.substr(0, MAX_BYTES);
        $(inputID).val(initialData);
    }

    const dropArea = $(inputID).get(0);
    dropArea.addEventListener("drop", drop, false);
}