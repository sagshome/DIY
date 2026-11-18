let ioomChart;


function wealth_detail(range, object_type, object_id, options, compare, scope) {

    let url = "/wealth/api/wealth_chart";
    let data = {};

    if (range !== undefined) {
        data['range'] = range
    }
    if (object_type !== undefined && object_type !== "") {
        data['object_type'] = object_type
        if (object_type === 'Account') {
            url = url;
            click_detail_url = '/wealth/account/' + object_id + '/table/'
        } else {
            click_detail_url = '/wealth/wealth_portfolio/' + object_id + '/table/'
        }
    } else {
        click_detail_url = '/wealth/data/'
    }
    if (object_id !== undefined) {
        data['object_id'] = object_id
    }
    if (options !== undefined) {
        data['options'] = options
    }
    if (compare !== undefined) {
        data['compare'] = compare
    }

    const ctx = document.getElementById('lineChart');

    // Destroy the existing chart
    if (ioomChart) {
        ioomChart.destroy();
    }

    $.ajax({
        url: url,
        data: data,

        success: function (response) {
            var datasets = [];

            labels = response.labels;
            data = response.data;


            if (
                data.values !== null &&
                data.values !== undefined &&
                data.values !== ""
            ) {
                datasets.push({
                    label: 'Value — green = above / red = below',
                    data: data.values,
                    fill: false,
                    pointRadius: 1,
                    pointHoverRadius: 5,
                    segment: {
                        borderColor: (ctx) => {
                            const prevValue = ctx.p0.parsed.y;
                            const nextValue = ctx.p1.parsed.y;

                            if (prevValue < response['starting'] || nextValue < response['starting']) {
                                return 'red';
                            }
                            return 'green';
                        }
                    },

                });
            }

            if (
                data.InflationValue !== null &&
                data.InflationValue !== undefined &&
                data.InflationValue !== ""
            ) {
                datasets.push({
                    label: 'Value (less inflation)',
                    data: data.InflationValue,
                    fill: false,
                    pointRadius: 1,
                    pointHoverRadius: 5,
                    borderDash: [6, 4],
                    segment: {
                        borderColor: (ctx) => {
                            const prevValue = ctx.p0.parsed.y;
                            const nextValue = ctx.p1.parsed.y;

                            if (prevValue < response['starting'] || nextValue < response['starting']) {
                                return 'red';
                            }
                            return 'green';
                        }
                    },

                });
            }
            if (
                data.InflationFunding !== null &&
                data.InflationFunding !== undefined &&
                data.InflationFunding !== ""
            ) {
                datasets.push({
                    label: 'Funding (matching CPI)',
                    data: data.InflationFunding,
                    backgroundColor: 'black',
                    borderColor: 'black',
                    pointRadius: 1,
                    pointHoverRadius: 5,
                    borderDash: [6, 4],
                    fill: false,


                });
            }

            if (
                data.Compare !== null &&
                data.Compare !== undefined &&
                data.Comapare !== ""
            ) {
                datasets.push({
                    label: compare,
                    data: data.Compare,
                    backgroundColor: 'blue',
                    borderColor: 'blue',
                    pointRadius: 1,
                    pointHoverRadius: 5,
                    fill: false,

                });
            }

            if (
                data.funding !== null &&
                data.funding !== undefined &&
                data.funding !== ""
            ) {
                datasets.push({
                    label: 'Funding',
                    data: data.funding,
                    backgroundColor: 'black',
                    borderColor: 'black',
                    pointRadius: 1,
                    pointHoverRadius: 5,
                    fill: false,
                });
            }

            ioomChart = new Chart("lineChart", {
                type: "line",

                data: {
                    labels: response.labels,
                    datasets: datasets,
                },

                options: {
                    onClick: function(event, elements, chart) {
                        if (elements.length === 0) {
                            return;  // Clicked somewhere other than a point
                        }

                        const element = elements[0];
                        const index = element.index;
                        const date = response.labels[index];

                        const url = new URL(click_detail_url, window.location.origin);

                        url.searchParams.set('range', range);
                        url.searchParams.set('explicit_date', date)
                        window.location.href = url.toString();

                    },

                    maintainAspectRatio: false,
                    responsive: true,

                    plugins: {
                        title: {
                            display: true,
                            text: 'Value Chart'
                        },
                        legend: {
                            labels: {
                                generateLabels: function(chart) {
                                    return chart.data.datasets.map((dataset, index) => ({
                                        text: dataset.label,
                                        datasetIndex: index,
                                        strokeStyle: dataset.borderColor || 'black',
                                        fillStyle: 'transparent',
                                        lineWidth: dataset.borderWidth || 2,
                                        lineDash: dataset.borderDash || [],
                                        hidden: !chart.isDatasetVisible(index)
                                    }));
                                }
                            }
                        }
                    }
                },
            });
        },
        error: function (data) {
            console.log('Error occurred' + data);
        }
    });
}

function wealth_data(range, object_type, object_id, options) {

    let url = "/wealth/api/wealth_data";
    let data = {};

    if (range !== undefined) {
        data['range'] = range
    }
    if (object_type !== undefined) {
        data['object_type'] = object_type
        if (object_type === 'Account') {
            url = url;
        }
    }
    if (object_id !== undefined) {
        data['object_id'] = object_id
    }
    if (options !== undefined) {
        data['options'] = options
    }
    const ctx = document.getElementById('lineChart');

    // Destroy the existing chart
    if (ioomChart) {
        ioomChart.destroy();
    }

    $.ajax({
        url: url,
        data: data,
        success: function (response) {

            const datasets = response.series.map((series, index) => ({

                label: series.name,
                data: series.data,
                borderColor: ioomColors[index % ioomColors.length],
                backgroundColor: ioomColors[index % ioomColors.length] + '40',
                fill: false,
                tension: 0.1
            }));

            ioomChart = new Chart("lineChart", {
                type: 'line',
                data: {
                    labels: response.labels,
                    datasets: datasets
                },
                options: {
                    maintainAspectRatio: false,
                    responsive: true,
                    plugins: {
                        title: {
                            display: true,
                            text: response.title
                        },
                    },
                    scales: {
                        x: {
                            stacked: response.stacked
                        },
                        y: {
                            stacked: response.stacked,
                            title: {
                                display: true,
                                text: response.ytitle
                            }
                        }
                    },

                }
            });
        },
        error: function (response) {
            console.log('Error occurred', response);
        }
    });
}

function summary_chart(range, object_type, object_id) {

    let url = "/wealth/api/wealth_summary";
    let data = {};

    if (range !== undefined) {
        data['range'] = range
    }
    if (object_type !== undefined) {
        data['object_type'] = object_type
        if (object_type === 'Account') {
            url = url;
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
                type: "line",
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
            });
        },
        error: function (data) {
            console.log('Error occurred' + data);
        }
    });
}

function update_cash(call_api) {
    if (call_api) {
        var account_value = $("#id_account").val();
        var date_value = $("#id_date").val();
        $.ajax({
            url: '/wealth/api/cash_value',
            async: false,  // make sure we wait for the update
            data: {
                'account_id': account_value,
                'date': date_value,
            },
            success: function (data) {   // `data` is the return of the `load_cities` view function
                document.getElementById('id_value').value = data['cash'];
            }
        });
    } else {
        document.getElementById('id_value').value = 0
    }
}

function update_equity() {
    var account_id = $("#id_account").val();
    var action_value = $("#id_action").val();
    var date_value = $("#id_date").val();

    if ($('#id_equity').hasClass("select2-hidden-accessible")) {
        $('#id_equity').select2('destroy');
    }

    $("#id_equity").select2({
        placeholder: "Select or type to search...",
        dropdownParent: $('#mainModal'),
        ajax: {
            url: '/wealth/api/equity_list',
            dataType: "json",
            delay: 250,
            data: function (params) {
                return {
                    'q': params.term,
                    'action': action_value,
                    'account_id': account_id,
                    'date': date_value,
                }
            },
            error: function (jqXHR, status, error) {
                console.error("AJAX Error: " + status + " - " + error);
                console.log("Response text: " + jqXHR.responseText);

                // Optionally return an empty results set to prevent Select2 from breaking
                return {results: []}
            },
            processResults: function (data) {
                return {results: data.results};
            }
        }
    });
    showDiv('equityRow')
}

function update_values() {

    var account_value = $("#id_account").val();
    var action_value = $("#id_action").val();
    var date_value = $("#id_date").val();
    var equity_value = $("#id_equity").val();

    $.ajax({                       // initialize an AJAX request
        url: '/wealth/api/xa_values',
        async: false,  // make sure we wait for the update
        data: {
            'action': action_value,
            'account_id': account_value,
            'date': date_value,
            'equity_id': equity_value,
        },
        success: function (data) {
            document.getElementById('id_price').value = data['price'];
            document.getElementById('id_quantity').value = data['shares'];
        }
    });
    if (equity_value === "") {
        hideDiv('quantityRow')
        showDiv('valueRow')
    } else {
        showDiv('quantityRow')
        hideDiv('valueRow')
    }
    showDiv('equityRow')
}

async function fetchOptions(query) {
    if (query.length < 2) return; // Avoid unnecessary API calls

    const response = await fetch(`/wealth/api/search/?q=${query}`);
    const data = await response.json();

    const container = document.getElementById("checkbox-container");
    container.innerHTML = ""; // Clear previous results

    data.results.forEach(item => {
        const label = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.value = item.symbol;
        checkbox.name = "options";
        label.appendChild(checkbox);
        label.appendChild(document.createTextNode(" " + item.symbol + " " + item.shortname));
        container.appendChild(label);
        container.appendChild(document.createElement("br"));
    });
}

function initModalControls(container) {
    show_hide()

    $(container).find('#id_action').off('mouseup').on('mouseup', show_hide)
    $(container).find('#id_action').off('change')
        .on('change', update_equity)
        .on('change', update_values);
    $(container).find('#id_equity').off('change')
        .on('change', update_equity)
        .on('change', update_values);
    $(container).find('#id_date').off('change').on('change', update_values)
    $(container).find('#id_repeat').off('change').on('change', show_hide)

    document.addEventListener("change", function (event) {
        if (event.target && event.target.type === "checkbox") {
            $.ajax({
                url: '/wealth/api/search_add',
                data: {
                    'symbol': event.target.value,
                },
                async: true,  // no need to wait
            });
        }
    });

    for (const el of document.getElementsByClassName("slow-submit-btn")) {
        el.addEventListener("click", function () {
            set_class_spinner(el.id)
        })
    }

    // old style
    var slow_btn = document.getElementById("slow-submit-btn")
    if (slow_btn) {
        slow_btn.addEventListener("click", function () {
            set_spinner()
        });
    }
}


/// Stuff for data pages  (used, main-data,  account, and portfolio
function populate_monthly_data(this_date, this_object, this_object_type) {
    const reconcileDate = this_date;
    const reconcileAcct = this_object;
    const reconcileType = this_object_type;

    let url;
    if (reconcileType === "Account") {
        url = `/wealth/account/${reconcileAcct}/reconcile_month/${reconcileDate}/`;
    } else if (reconcileType === "Portfolio") {
        url = `/wealth/portfolio/${reconcileAcct}/reconcile_month/${reconcileDate}/`;
    } else {
        url = `/wealth/reconcile_month/${reconcileDate}/`;
    }

    sessionStorage.setItem('selectedReconciliationDate', reconcileDate);
    sessionStorage.setItem('selectedReconciliationAcct', reconcileAcct);
    sessionStorage.setItem('selectedReconciliationType', reconcileType);

    fetch(url)
        .then(response => response.text())
        .then(html => {
            document.getElementById("reconcile-pane").innerHTML = html;
        })
        .catch(error => console.error(error));
}

// Support for Next/Previous pages
document.addEventListener('click', async function (event) {

    if (event.target.matches('#jump-previous')) {
        event.preventDefault();
        const date = event.target.dataset.date;
        if (date !== "") {
            const selectedAcct = sessionStorage.getItem('selectedReconciliationAcct');
            const selectedType = sessionStorage.getItem('selectedReconciliationType');
            if (selectedAcct !== null & selectedType !== null) {
                populate_monthly_data(date, selectedAcct, selectedType);
            }
        }
    }
    if (event.target.matches('#jump-next')) {
        event.preventDefault();
        const date = event.target.dataset.date;
        if (date !== "") {
            const selectedAcct = sessionStorage.getItem('selectedReconciliationAcct');
            const selectedType = sessionStorage.getItem('selectedReconciliationType');
            if (selectedAcct !== null & selectedType !== null) {
                populate_monthly_data(date, selectedAcct, selectedType);
            }
        }
    }
});
