let timerInterval;

function startTimer(duration, display) {
    let start = Date.now(), diff, minutes, seconds;
    timerInterval = setInterval(() => {
        diff = duration - (((Date.now() - start) / 1000) | 0);
        minutes = (diff / 60) | 0;
        seconds = (diff % 60) | 0;
        display.textContent = `${minutes.toString().padStart(2,'0')}:${seconds.toString().padStart(2,'0')}`;
    }, 1000);
}

document.getElementById("recordBtn").onclick = async () => {
    document.getElementById("status").innerText = "Recording...";
    startTimer(15, document.getElementById("timer"));

    try {
        let response = await fetch("/record", { method: "POST" });
        clearInterval(timerInterval);
        document.getElementById("timer").textContent = "00:00";

        let data = await response.json();
        if(data.error){
            document.getElementById("status").innerText = data.error;
        } else {
            document.getElementById("status").innerText = "Recording complete!";
            document.getElementById("transcript").innerText = data.transcript;
            document.getElementById("summary").innerText = data.summary;
        }
    } catch(err) {
        clearInterval(timerInterval);
        document.getElementById("status").innerText = "Error: " + err;
    }
};
