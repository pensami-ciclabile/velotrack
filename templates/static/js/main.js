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

/* Extra rides — pick value based on day of week */
document.addEventListener("DOMContentLoaded", function () {
    var el = document.querySelector("[data-rides-weekday]");
    if (!el) return;
    var day = new Date().getDay();
    var key = day === 0 ? "sunday" : day === 6 ? "saturday" : "weekday";
    var rides = el.getAttribute("data-rides-" + key);
    if (!rides) return;
    var span = el.querySelector(".tl-rides-value");
    if (span) span.textContent = rides;
});

/* Commute calculator */
document.addEventListener("DOMContentLoaded", function () {
    var dataEl = document.getElementById("commute-data");
    if (!dataEl) return;
    var data = JSON.parse(dataEl.textContent);
    var lineSelect = document.getElementById("commute-line-select");
    var fromSelect = document.getElementById("commute-from-select");
    var toSelect = document.getElementById("commute-to-select");
    var monthValue = document.getElementById("commute-month-value");
    var nodata = document.getElementById("commute-nodata");
    var currentItem = null;

    // Populate line dropdown
    data.forEach(function (item) {
        var opt = document.createElement("option");
        opt.value = item.line;
        opt.textContent = "Linea " + item.line + " / Line " + item.line;
        lineSelect.appendChild(opt);
    });

    function populateStopSelect(sel, stops, placeholder) {
        sel.innerHTML = "";
        var def = document.createElement("option");
        def.value = "";
        def.disabled = true;
        def.selected = true;
        def.textContent = placeholder;
        sel.appendChild(def);
        stops.forEach(function (name, i) {
            var opt = document.createElement("option");
            opt.value = i;
            opt.textContent = name;
            sel.appendChild(opt);
        });
        sel.disabled = false;
    }

    function updateResult() {
        if (!currentItem || currentItem.tl_wait === null) return;
        var fromIdx = parseInt(fromSelect.value, 10);
        var toIdx = parseInt(toSelect.value, 10);
        if (isNaN(fromIdx) || isNaN(toIdx) || fromIdx === toIdx) {
            monthValue.textContent = "\u2014";
            return;
        }
        var totalStops = currentItem.stops.length;
        var fraction = Math.abs(toIdx - fromIdx) / (totalStops - 1);
        var oneWay = currentItem.tl_wait * fraction;
        var monthly = Math.round(oneWay * 2 * 22 / 60);
        monthValue.textContent = monthly;
    }

    lineSelect.addEventListener("change", function () {
        var lineNum = parseInt(lineSelect.value, 10);
        currentItem = data.find(function (d) { return d.line === lineNum; });
        monthValue.textContent = "\u2014";
        nodata.style.display = "none";
        if (!currentItem || currentItem.tl_wait === null) {
            fromSelect.innerHTML = "<option value='' disabled selected>--</option>";
            toSelect.innerHTML = "<option value='' disabled selected>--</option>";
            fromSelect.disabled = true;
            toSelect.disabled = true;
            if (currentItem) nodata.style.display = "block";
            return;
        }
        populateStopSelect(fromSelect, currentItem.stops, "Partenza / From");
        populateStopSelect(toSelect, currentItem.stops, "Arrivo / To");
    });

    fromSelect.addEventListener("change", updateResult);
    toSelect.addEventListener("change", updateResult);
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
