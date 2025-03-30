let barChart = undefined;
    let barLabels = undefined;

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
        let time_period = barLabels[res[0].index];
        let search_value = barChart.legend.legendItems[res[0].datasetIndex].text
        let url = '/expenses/main/?span=' + time_period + '&category=' + search_value;
        window.location.href = url; // Navigate to the URL
    }

    function bar_chart(search_data, title_text, canvas) {
        $.ajax({
            url: "/expenses/ajax/expense-bar",
            data: search_data,
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

    function pie_chart(search_data, title_text, canvas) {
        $.ajax({
            url: "/expenses/ajax/expense-pie",
            data: search_data,
            success: function (data) {
                  new Chart(canvas, {
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

    function expense_charts(type, canvas, text, income = false) {
              var data = {
                'search_category': $("#id_search_category").val(),
                'search_subcategory': $("#id_search_subcategory").val(),
                'search_ignore': $("#id_search_ignore").val(),
                'search_start_date': $("#id_search_start_date").val(),
                'search_end_date': $("#id_search_end_date").val(),
                'search_amount': $("#id_search_amount_qualifier").val(),
                'search_amount_qualifier': $("#id_search_amount").val(),
                'search_description': $("#id_search_description").val(),
              }

              if (type == 'bar') {
                  bar_chart(data, text, canvas);
              } else {
                  pie_chart(data, text, canvas);
              }
        }