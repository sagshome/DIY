// Setup data for CallBack
const wealthCanvas = document.getElementById('wealthPie');
const wealthCtx = wealthCanvas.getContext('2d');
let wealthData = undefined
let wealthChart = undefined

wealthCanvas.onclick = (evt) => {
    const res = wealthChart.getElementsAtEventForMode(
        evt,
        'nearest',
        {intersect: true},
        true
    );

    // If didn't click on a bar, `res` will be an empty array
    if (res.length === 0) {
        return;
    }
    const url = wealthData.options_links[res[0].index];
    window.location.href = wealthData.options_links[res[0].index]; // Navigate to the URL
}

const cashCanvas = document.getElementById('cashChart');
const cashCtx = cashCanvas.getContext('2d');
let cashChart = undefined;
let cashLabels = undefined;
const expense_url = "/expenses/main"

cashCanvas.onclick = (evt) => {
    let res = cashChart.getElementsAtEventForMode(
        evt,
        'nearest',
        {intersect: true},
        true
    );

    // If didn't click on a bar, `res` will be an empty array
    if (res.length === 0) {
        return;
    }
    // res.datasetIndex = 0 = Expenses and 1 = Income
    time_period = cashLabels[res[0].index];
    search_value = cashChart.legend.legendItems[res[0].datasetIndex].text
    var url = expense_url + '?span=' + time_period
    if (search_value === "Income") {
        url = url + '&category=' + search_value
    }
    window.location.href = url; // Navigate to the URL

    //const url = wealthData.options_links[res[0].index];
    //window.location.href = url; // Navigate to the URL
}

function build_wealth_pie(chart_url) {
    $.ajax({
        url: chart_url,
        success: function (data) {
            wealthData = data;
            wealthChart = new Chart(wealthCtx, {
                type: "pie",
                data: {
                    labels: wealthData['labels'],
                    datasets: [{
                        data: wealthData['data'],
                        backgroundColor: wealthData['colors'],
                    }]
                },
                options: {
                    onClick: (event, elements) => {
                        if (elements.length > 0) {
                            const clickedElementIndex = elements[0]._index; // Get the clicked slice index
                            const url = data.options_links[clickedElementIndex]; // Get the corresponding URL
                            if (url) {
                                window.location.href = url; // Navigate to the URL
                            }
                        }
                    },
                    plugins: {
                        title: {
                            display: true,
                            text: 'Wealth Value by Portfolio/Account'
                        },
                        legend: {
                            display: false,
                            position: 'right',
                            align: 'center'
                        }  // legend
                    },
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: {
                        animateScale: true,
                        animateRotate: true
                    },

                }  // options
            })  // chart
        } // success
    });
}// ajax

function cash_flow_chart(chart_url, trends, period, span) {

    $.ajax({
        url: chart_url,
        data: {span: span, period: period, trends: trends},  // 3 years of data
        success: function (data) {
            cashLabels = data['labels'],
                cashChart = new Chart(cashCtx, {

                    type: 'line',
                    data: {
                        labels: data['labels'],
                        datasets: data['datasets']
                    },
                    options: {
                        title: {
                            display: true,
                            text: "Cash Flow"
                        },
                        responsive: true,  // Make the chart responsive to screen resizing
                        scales: {
                            y: {
                                beginAtZero: true  // Start Y-axis from zero
                            }
                        },
                        plugins: {
                            legend: {
                                display: true,
                                position: 'top',  // Position the legend at the top
                                labels: {
                                    boxHeight: 5,
                                }
                            },
                            tooltip: {
                                enabled: true,  // Enable tooltips when hovering over the chart
                                backgroundColor: 'rgba(0, 0, 0, 0.7)',  // Tooltip background color
                                titleColor: 'white',  // Title text color in the tooltip
                                bodyColor: 'white'  // Body text color in the tooltip
                            }
                        },
                        elements: {
                            line: {
                                borderWidth: 4  // Line width
                            },
                            point: {
                                radius: 5,  // Point size on the line
                            }
                        }
                    }
                });
        } // success
    });  // ajax
    //};
}
