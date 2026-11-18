let barChart = undefined;
let barLabels = undefined;
let pieChart = undefined;
let pieLabels = undefined;
let searched_category = undefined;

document.getElementById('barChart').onclick = (evt) => {
    let res = barChart.getElementsAtEventForMode(
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
    const url = new URL(window.location.href);
    const time_period = barLabels[res[0].index];
    const search_value = barChart.legend.legendItems[res[0].datasetIndex].text
    url.searchParams.set('month', time_period);
    window.location.href = url; // Navigate to the URL
}

document.getElementById('pieChart').onclick = (evt) => {
    const res = pieChart.getElementsAtEventForMode(
        evt,
        'nearest',
        {intersect: true},
        true
    );

    // If didn't click on a bar, `res` will be an empty array
    if (res.length === 0) {
        return;
    }
    const pieSlice = pieLabels[res[0].index]
    const params = new URLSearchParams(window.location.search);
    const url = new URL(window.location.href);

    if (params.get('search_category') === null || params.get('search_category') === '- ALL -') {
        url.searchParams.set('search_category', pieSlice);
        url.searchParams.delete('search_subcategory')
    } else {
        url.searchParams.set('search_subcategory', pieSlice);
    }
    window.location.href = url; // Navigate to the URL
}

function bar_chart(title_text, canvas) {
    $.ajax({
        url: "/expenses/ajax/expense-bar" + window.location.search,
        success: function (data) {
            barLabels = data['labels'],
            barChart = new Chart(canvas,
                {
                    type: "bar",
                    data: {
                        labels: data['labels'],
                        datasets: data['datasets']
                    },
                    options: {
                        plugins: {
                            title: {
                                display: true,
                                text: 'Expanse Chart'
                            },
                            legend: {
                                display: true,
                                position: 'top',
                                align: 'center'
                            }  // legend
                        },

                        maintainAspectRatio: false,
                        responsive: true,
                    },
                    scales: {
                        xAxes: [{
                            stacked: false // this should be set to make the bars stacked
                        }],
                        yAxes: [{
                            stacked: true // this also..
                        }]
                    }

            });
        }
    });
};

function pie_chart(title_text, canvas) {
    $.ajax({
        url: "/expenses/ajax/expense-pie" + window.location.search,
        success: function (data) {
              pieLabels = data['labels'],
              pieChart = new Chart(canvas, {
                    type: "pie",
                    data: {
                        labels: data['labels'],
                        datasets: [{
                          data: data['data'],
                          backgroundColor: data['colors'],
                        }]
                    },
                    options: {
                        plugins: {
                            title: {
                                display: true,
                                text: 'Expense totals by Categroy/SubCategory'
                            },
                            legend: {
                                display: false,
                                position: 'right',
                                align: 'center'
                            }  // legend
                        },

                        responsive: false,
                        maintainAspectRatio: false,
                        animation: {
                            animateScale: true,
                            animateRotate: true
                        },

                    }  // options
              })  // chart
        } // success
      });  // ajax
} // function

function expense_charts(type, canvas, text) {

              if (type === 'bar') {
                  bar_chart(text, canvas);
              } else {
                  pie_chart(text, canvas);
              }
        }