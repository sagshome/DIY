    function setValues(button, cat, sub) {
        //  This is used to set shortcut values
        //  button is a font awsome font
        //  category is the category to select
        //  subcategory is the subcategory to select
        //  todo:  this should fire the choice list update on subcategory
        let my_cell = $(button).closest('td');
        let cat_cell = my_cell.next('td');
        let cat_id = cat_cell.children()[0].getAttribute('id');
        let sub_id = cat_cell.next('td').children()[0].getAttribute('id');

        for (let option of document.getElementById(cat_id).options) {
            if (option.text === cat) {
                option.selected = true;
                break;
            }
        }

        for (let option of document.getElementById(sub_id).options) {
            if (option.text === sub) {
                option.selected = true;
                break;
            }
        }
    }

    //const barCanvas = document.getElementById('barChart');
    //const barCtx = barCanvas.getContext('2d');




