function show_hide_small() {
    const x = document.getElementById("navSmall");
    if (x.className.indexOf("w3-show") === -1) {
        x.className += " w3-show";
    } else {
        x.className = x.className.replace(" w3-show", "");
    }
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

