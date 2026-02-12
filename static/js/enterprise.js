

/* CLOCK */

setInterval(()=>{

document.getElementById("clock").innerHTML =
new Date().toLocaleString("fr-FR");

},1000);



/* DOT ANIMATION */

function animateDots(){

const dots=document.querySelectorAll(".dot");

dots.forEach((d,i)=>{

setTimeout(()=>{

d.classList.add("active");

},i*120);

});

}



/* LOGIN */

function login(){

animateDots();

setTimeout(()=>{

window.location="/home";

},700);

}
