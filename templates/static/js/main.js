/* Traffic light hours highlight — pick value based on day of week */
document.addEventListener("DOMContentLoaded", function () {
    var el = document.querySelector(".tl-highlight");
    if (!el) return;
    var day = new Date().getDay(); // 0=Sun, 6=Sat
    var key = day === 0 ? "sunday" : day === 6 ? "saturday" : "weekday";
    var hours = el.getAttribute("data-" + key);
    if (!hours) return;
    var span = el.querySelector(".tl-hours-value");
    if (span) span.textContent = hours;
    var labels = el.querySelectorAll(".tl-day-label");
    var labelIt = key === "sunday" ? "domenica" : key === "saturday" ? "sabato" : "giorno feriale";
    var labelEn = key === "sunday" ? "Sunday" : key === "saturday" ? "Saturday" : "weekday";
    for (var i = 0; i < labels.length; i++) {
        var parent = labels[i].closest("[class*='i18n-']");
        labels[i].textContent = parent && parent.classList.contains("i18n-en") ? labelEn : labelIt;
    }
});

/* Comparison chart for the lines page. */
document.addEventListener("DOMContentLoaded", function () {
    var canvas = document.getElementById("comparison-chart");
    if (!canvas) return;

    var lines = JSON.parse(canvas.getAttribute("data-lines"));
    if (!lines || !lines.length) return;

    var labels = lines.map(function (l) { return l.display_name; });
    var avgSpeeds = lines.map(function (l) { return l.stats.speed.avg_moving; });
    var totalDelays = lines.map(function (l) { return l.stats.total_delay; });

    new Chart(canvas, {
        type: "bar",
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Avg Speed (km/h)",
                    data: avgSpeeds,
                    backgroundColor: "rgba(26, 111, 181, 0.7)",
                    yAxisID: "y"
                },
                {
                    label: "Total Delay (s)",
                    data: totalDelays,
                    backgroundColor: "rgba(220, 60, 60, 0.7)",
                    yAxisID: "y1"
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: "top" }
            },
            scales: {
                y: {
                    type: "linear",
                    position: "left",
                    title: { display: true, text: "Avg Speed (km/h)" },
                    beginAtZero: true
                },
                y1: {
                    type: "linear",
                    position: "right",
                    title: { display: true, text: "Total Delay (s)" },
                    beginAtZero: true,
                    grid: { drawOnChartArea: false }
                }
            }
        }
    });
});
