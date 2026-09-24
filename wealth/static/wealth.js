
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
            error: function(data) {
                console.log('Error occurred' + data);
            }
      });
}


function generic_wealth_chart(range, object_type, object_id, options, compare, scope) {

      let url = "/wealth/api/generic_wealth";
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

      if (compare !== undefined) {
          data['compare'] = compare
      }

      if (scope !== undefined) {
          data['scope'] = scope
      }

      $.ajax({
            url: url,
            data: data,
            success: function (data) {
                new Chart("lineChart", {
                    type: "line",
                    data: {
                        labels: data['labels'],
                        datasets: [
                            {
                                data: data['data'],
                                fill: false,
                                segment: {
                                    borderColor: (ctx) => {
                                        const prevValue = ctx.p0.parsed.y;
                                        const nextValue = ctx.p1.parsed.y;

                                        if (prevValue < data['starting'] || nextValue < data['starting']) {
                                            return 'red';
                                        }
                                         return 'green';
                                    }
                                },
                            },
                        ],
                    },
                    options: {
                        maintainAspectRatio: false,
                        responsive: true,
                        plugins: {
                            title: {
                                display: true,
                                text: 'Current Value Chart'
                            },
                            legend: {
                                display: false,
                            },
                        }
                    },
                });
            },
            error: function(data) {
                console.log('Error occurred' + data);
            }
      });
}

function zero_summary_chart(range, object_type, object_id, options) {

      let url = "/wealth/api/zero_wealth_summary";
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
      $.ajax({
            url: url,
            data: data,
            success: function (data) {
                new Chart("lineChart", {
                    type: "line",
                    data: {
                        labels: data['labels'],
                        datasets: [
                            {
                                data: data['data'],
                                fill: false,
                                segment: {
                                    borderColor: (ctx) => {
                                        const prevValue = ctx.p0.parsed.y;
                                        const nextValue = ctx.p1.parsed.y;

                                        if (prevValue < data['starting'] || nextValue < data['starting']) {
                                            return 'red';
                                        }
                                         return 'green';
                                    }
                                },
                            },
                        ],
                    },
                    options: {
                        maintainAspectRatio: false,
                        responsive: true,
                        plugins: {
                            title: {
                                display: true,
                                text: 'Current Value Chart'
                            },
                            legend: {
                                display: false,
                            },
                        }
                    },
                });
            },
            error: function(data) {
                console.log('Error occurred' + data);
            }
      });
}

function hideDiv(divId) {
   var div = document.getElementById(divId);
   if (div === null) {
   }
   else {
    div.style.display = "none";
    }
}

function showDiv(divId) {
    var div = document.getElementById(divId);
    if (div === null) {
    }
    else {
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
    var t = setInterval(function() {
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
                return { results: [] }
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

    document.addEventListener("change", function(event) {
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
        slow_btn.addEventListener("click", function() {
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

        console.log("modal form submit intercepted");
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


