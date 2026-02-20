Start-Process powershell -WorkingDirectory "runtime-ui" -ArgumentList "-NoExit", "-Command", "npm run dev"

Start-Process powershell -WorkingDirectory "." -ArgumentList `
    "-NoExit", `
    "-Command", "& '.\ONNX host service\env\Scripts\uvicorn.exe' onnx_host.main:app --reload"