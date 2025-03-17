function cost_value_chart(api, object_id, object_type, equity_id) {
    $(document).ready(function () {
        $.ajax({
            url: api,
            data: {
                'object_id': object_id,
                'object_type': object_type,
                'symbol': equity_id,
            },
            success: function (data) {
                let lineChart = new Chart("lineChart", {
                    type: "line",
                    data: data,
                    options: {
                        scales: {
                            y: {
                                beginAtZero: true
                            },
                        },
                        elements: {
                            point: {
                                radius: 2
                            }
                        },
                        responsive: true,
                        maintainAspectRatio: false,
                        title: {
                            display: true,
                            text: "Return vs Cost"
                        },
                        legend: {
                            display: true,
                            position: 'top',
                            align: 'center'
                        },
                    }
                });
            }
        });
    });
}

function summary_chart(object_type, object_id) {

      let url = "/stocks/api/wealth_summary";
      let data = {};
      if (object_type !== undefined) {
          data['object_type'] = object_type
          if (object_type === 'Account') {
              url = "/stocks/api/equity_summary";
          }
      }
      if (object_id !== undefined) {
          data['object_id'] = object_id

      }
      $.ajax({
            url: url,
            data: data,
            success: function (data) {
                new Chart("lineChart", {
                    type: "bar",
                    data: {
                        labels: data['labels'],
                        datasets: data['datasets'],
                    },
                    options: {
                        maintainAspectRatio: false,
                        responsive: true,
                        title: {
                            display: true,
                            text: 'Account Accumulation Chart'
                        },
                        legend: {
                            display: true,
                            position: 'right',
                            align: 'center'
                        },
                    },
                    scales: {
                        xAxes: [{
                            stacked: true // this should be set to make the bars stacked
                        }],
                    }
                });
            },
        error: function(data) {
            console.log('Error occurred' + data);
        }
      });
}