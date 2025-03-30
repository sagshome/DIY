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

    function get_subcategory_choices() {
        $(document).ready(function () {
            $("#id_category").change(function () {
                let categoryId = $(this).val();  // get the selected Category ID from the HTML input

                $.ajax({                       // initialize an AJAX request
                    url: '/expenses/ajax/load-subcategories/',
                    data: {
                        'category': categoryId       // add the country id to the GET parameters
                    },
                    success: function (data) {   // `data` is the return of the `load_cities` view function
                        $("#id_subcategory").html(data);  // replace the contents of the city input with the data that came from the server
                    },
                    error: function (ts) {
                        console.log(ts.responseText)
                    }
                });
            });
        });
    }

    function set_change_callback() {
        $('.diy-category').each(function (index, element) {  // Invalidate subcategory when category changed
            document.getElementById(this.id).addEventListener("change", function () {
                let row_id = this.id.slice(8, this.id.length - 9);  // Just the number part
                let category_id = document.getElementById("id_form-" + row_id + "-category")
                let subcategory_id = document.getElementById("id_form-" + row_id + "-subcategory")
                let category = $(category_id).val()
                $.ajax({
                    url: '/expenses/ajax/load-subcategories/',
                    data: {category: category},
                    success: function (data) {
                        $(subcategory_id).html(data);
                    },
                    error: function (ts) {
                        console.log(ts.responseText)
                    }
                })  // ajax
            })  // add Event
        });  // for each
    }

    //const barCanvas = document.getElementById('barChart');
    //const barCtx = barCanvas.getContext('2d');




