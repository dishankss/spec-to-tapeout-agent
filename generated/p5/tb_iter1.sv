module tb;
  localparam N = 8;
  localparam WIDTH = 8;

  logic rst;
  logic [N-1:0] A;
  logic [N-1:0] B;
  logic [2*WIDTH+3:0] dot_out;
  logic valid;

  dot_product #(.N(N), .WIDTH(WIDTH)) uut (
    .rst(rst), .A(A), .B(B), .dot_out(dot_out), .valid(valid)
  );

  integer cycle;
  initial begin
    rst = '0;
    A = '0;
    B = '0;
    rst = 1;
    #10;
    rst = 0;

    #1;
    $display("OBS dot_out=%b", dot_out);
    $display("OBS valid=%b", valid);
    #10;
    $finish;
  end
endmodule
