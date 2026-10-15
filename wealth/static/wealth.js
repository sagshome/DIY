const colors = [
    '#4e79a7',
    '#f28e2b',
    '#59a14f',
    '#e15759',
    '#b07aa1',
    '#76b7b2',
    '#edc949',
];

let ioomChart;

function getCSRFToken() {
    const name = "csrftoken=";
    return document.cookie
        .split(";")
        .map(c => c.trim())
        .find(c => c.startsWith(name))
        ?.substring(name.length) || null;
}

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
                borderColor: colors[index % colors.length],
                backgroundColor: colors[index % colors.length] + '40',
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

function hideDiv(divId) {
    var div = document.getElementById(divId);
    if (div === null) {
    } else {
        div.style.display = "none";
    }
}

function showDiv(divId) {
    var div = document.getElementById(divId);
    if (div === null) {
    } else {
        div.style.display = "table-row";
    }
}

function show_hide() {

    let action_value = $("#id_action").val();
    let repeat_value = $("#id_repeat").val();
    let equity_value = $("#id_equity").val();

    if ((action_value === 'FUND' || action_value === 'REDEEM')) {
        hideDiv('equityRow');
        hideDiv('priceRow');
        hideDiv('quantityRow');
        showDiv('valueRow');

        hideDiv('toAccountRow');
        showDiv('repeatRow')

    } else if ((action_value === 'TRANS_IN' || action_value === 'TRANS_OUT')) {  // Transfer In/Out
        showDiv('equityRow');
        hideDiv('priceRow');
        hideDiv('repeatRow');
        if (equity_value === "") {
            showDiv('valueRow');
            hideDiv('quantityRow')
        } else {
            showDiv('quantityRow');
            hideDiv('valueRow')
        }
        showDiv('toAccountRow');
    } else if ((action_value === 'BUY' || action_value === 'SELL' || action_value === 'REDIV')) {
        showDiv('equityRow');
        showDiv('priceRow');
        showDiv('quantityRow');
        hideDiv('valueRow');

        hideDiv('toAccountRow');
        hideDiv('repeatRow')
    } else if ((action_value === 'VALUE' || action_value === 'BALANCE')) {
        hideDiv('equityRow');
        hideDiv('priceRow');
        hideDiv('quantityRow');
        showDiv('valueRow');
        hideDiv('repeatRow')
        hideDiv('toAccountRow')

    } else {

        hideDiv('equityRow');
        hideDiv('priceRow');
        hideDiv('quantityRow');
        hideDiv('valueRow');
        hideDiv('repeatRow')
        hideDiv('toAccountRow')
    }
    if (repeat_value === 'yes') {
        showDiv('numberRow');
    } else {
        hideDiv('numberRow');
    }
}

function set_spinner() {
    showDiv("spinner-text")
    var t = setInterval(function () {
        var ele = document.getElementById('spinner-text');
        ele.style.opacity = (ele.style.opacity == 0 ? 1 : 0);
    }, 1000);
};

function clear_spinner() {
    hideDiv("spinner-text")
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

    var slow_btn = document.getElementById("slow-submit-btn")
    if (slow_btn) {
        slow_btn.addEventListener("click", function () {
            set_spinner()
        });
    }
}


async function processTransactionResult(form) {
    clear_spinner()
    const res = await fetch(form.getAttribute('action'), {
        method: "POST",
        body: new FormData(form),
    });

    const data = await res.json();

    if (data.redirect) {
        window.location.href = data.redirect;
    } else {
        Object.entries(data.errors).forEach(([field, messages]) => {

            let input = document.querySelector(`[name="${field}"]`);
            if (!input) {
                input = document.querySelector(`[name="ioom_nonfield_errors"]`)
                if (!input) {
                    console.log(field, messages)
                } else {
                    input.classList.add('alert')
                    input.classList.add('alert-warning')
                    input.style.whiteSpace = 'pre-wrap'
                    input.textContent = field + ": " + messages.join(' ') + "\n";

                }
            } else {
                input.classList.add('is-invalid');
                // bootstrap error div
                let errorDiv = input.parentNode.querySelector('.invalid-feedback');
                if (!errorDiv) {
                    errorDiv = document.createElement('div');
                    errorDiv.className = 'invalid-feedback';
                    input.parentNode.appendChild(errorDiv);
                }

                errorDiv.textContent = messages.join(' ');
            }
        });
    }
}


document.addEventListener('submit', function (e) {
    const modal = document.getElementById('mainModal');

    // ignore if not inside modal
    if (!modal.contains(e.target)) return;

    if (e.target.matches('.ioom_modal_form')) {

        e.preventDefault();

        input = document.querySelector(`[name="ioom_nonfield_errors"]`)
        if (input) {
            input.classList.remove('alert')
            input.classList.remove('alert-warning')
            input.style.whiteSpace = 'pre-wrap'
            input.textContent = ""
        }
        processTransactionResult(e.target);
    }
});


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

/// Stuff for reconcile_month.html
document.addEventListener('submit', function (event) {
    if (event.target.matches('#reconcile-form')) {
        event.preventDefault();

        const form = event.target;
        fetch(form.action, {
            method: 'POST',
            body: new FormData(form)
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error('POST failed');
                }
                return response.json();
            })
            .then(data => {
                if (data.ok) {
                    // POST succeeded
                } else {
                    // Django rejected the POST
                    console.log(data);
                }
            })
            .catch(error => console.error(error));
    }
});

/// Styff for Transaction List

document.addEventListener('click', async function (event) {
    const icon = event.target.closest('.ioom-delete-action');

    if (icon) {
        event.preventDefault();

        const row = icon.closest('tr');
        if (!row) return;

        row.classList.add('deleting-row');

        try {
            const response = await fetch(
                `/wealth/api/quick_delete?action_id=${row.dataset.id}&action_type=${row.dataset.key}`,
                {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCSRFToken(),
                        'Content-Type': 'application/json'
                    }
                }
            );

            if (!response.ok) {
                console.error('Delete failed' + response.status);
                row.classList.remove('deleting-row');
                return;
            }

            row.classList.add('deleted-row');
            icon.style.display = 'none';

        } catch (err) {
            console.error('Request error', err);
            row.classList.remove('deleting-row');
        }
    }
})
