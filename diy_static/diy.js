const ioomColors = [
    '#4e79a7',
    '#f28e2b',
    '#59a14f',
    '#e15759',
    '#b07aa1',
    '#76b7b2',
    '#edc949',
];

function trimPathSearch(path, opt) {
    // Remove opt from the path if it is found
    const search_on = opt + '='

    if (path === undefined || path === null ||path.length === 0 || path[0] !== '?') {
        return path  // not a valid URL search string
    }

    path = path.slice(1)
    items = path.split('&')
    let result = items
        .filter(item => item.substring(0, search_on.length) !== search_on)
        .join('&');
    if (result.length > 0) {
        result = '?' + result
    }
    return result
}

function getCSRFToken() {
    const name = "csrftoken=";
    return document.cookie
        .split(";")
        .map(c => c.trim())
        .find(c => c.startsWith(name))
        ?.substring(name.length) || null;
}

function toggle_help() {
    const help_page = document.getElementById('DIYHelpContent');
    if (help_page.style.display === 'none') {
        help_page.style.display = 'block';
    } else {
        help_page.style.display = 'none';
    }
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
        div.style.display = "block";
    }
}

// VERY Basic Spinner
document.addEventListener('click',function (event) {
    // Flip the chevron when the chart-colapse-button if pressed
    if (event.target.matches('.slow-submit-btn')) {
        that_id = event.target.id
        set_class_spinner(that_id)
    }
});

function set_class_spinner(spinner_id) {
    that_id = spinner_id + '-spinner'
    showDiv(that_id)
        var t = setInterval(function () {
        var ele = document.getElementById(that_id);
        ele.style.opacity = (ele.style.opacity == 0 ? 1 : 0);
    }, 1000);
}

function clear_class_spinner(spinner_id) {
    that_id = spinner_id + '-spinner'
    hideDiv(this_id)
}

function toggle_chevron() {
    // locate the ioom-chart-colapse-text element and switch the chevron direction
    const e = document.getElementById('ioom-chart-colapse-text')
    if (e === null) {
    } else {
        if (e.classList.contains('bi-chevron-up')) {
            e.classList.remove('bi-chevron-up')
            e.classList.add('bi-chevron-down')
        } else {
            e.classList.remove('bi-chevron-down')
            e.classList.add('bi-chevron-up')
        }
    }
}

// Generic Code to deal with ajax,  calling modal dialogs/forms

// Error handler (for form, formsets)
function displayFormErrors(errors) {
    // Clear errors from the previous attempt
    document.querySelectorAll('.is-invalid').forEach(el => {
        el.classList.remove('is-invalid');
    });

    document.querySelectorAll('.invalid-feedback').forEach(el => {
        el.textContent = '';
    });

    errors.forEach(error => {
        // Django formset field name, e.g. form-0-quantity
        const inputName = `form-${error.index}-${error.field}`;
        const input = document.querySelector(
            `[name="${inputName}"]`
        );

        if (!input) return;

        input.classList.add('is-invalid');
        input.textContext = error.messages.join(' ');
        const feedback = input.parentElement.querySelector('.invalid-feedback');

        if (feedback) {
            feedback.textContent = error.messages.join(' ');
        }
    });
};

// Support quick cancel base on adding the call ioom-cancel
document.addEventListener('click', function (event) {
    const modal = document.getElementById('mainModal');
    // ignore if not inside modal
    if (!modal.contains(event.target)) return;

    if (event.target.matches('.ioom-cancel')) {
        event.preventDefault();
        const form = event.target;
        const modalElement = form.closest('.modal');
        if (modalElement) {
            bootstrap.Modal.getInstance(modalElement)?.hide();
        }
    }
});



// Support POST action based on class generic_modal_form

document.addEventListener('submit', function (event) {
    const modal = document.getElementById('mainModal');
    // ignore if not inside modal
    if (!modal.contains(event.target)) return;

    if (event.target.matches('.generic_modal_formset')) {

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
                return response.json();  // Ugly in production todo: return a redirect to a nice error page

            })
            .then(data => {
                if (data.ok) {
                    // POST succeeded
                    if (data.redirect) {
                        window.location.href = data.redirect;
                    } else if (data.close) {
                        const modalElement = form.closest('.modal');
                        if (modalElement) {
                            bootstrap.Modal.getInstance(modalElement)?.hide();
                        }
                    }
                } else {
                    // Django rejected the POST
                    // console.log(data);
                    displayFormErrors(data.errors);
                }
            })
            .catch(error => console.error(error));
    }
});

// Quick Delete - based on
//      <tr data-id="{{loopvar.id}}" data-key="SomeKey" class="ioom-action-row"> and
//      <td <i class="bi bi-trash ioom-delete-action"></i>
//

document.addEventListener('click',function (event) {
    // Flip the chevron when the chart-colapse-button if pressed
    if (event.target.matches('#chart-colapse-button')) {
        event.preventDefault();
        toggle_chevron()
    }
});

document.addEventListener('click', async function (event) {
    const icon = event.target.closest('.ioom-delete-action');

    if (icon) {
        event.preventDefault();

        const row = icon.closest('tr');
        if (!row) return;

        row.classList.add('deleting-row');

        try {
            const response = await fetch(
                `/base/api/quick_delete?action_id=${row.dataset.id}&action_type=${row.dataset.key}`,
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
