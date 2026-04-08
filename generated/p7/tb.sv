module tb;
  localparam WIDTH = 8;

  logic rst;
  logic enable;
  logic [WIDTH-1:0] x_in;
  logic [2*WIDTH-1:0] exp_out;

  exp_fixed_point #(.WIDTH(WIDTH)) uut (
    .rst(rst), .enable(enable), .x_in(x_in), .exp_out(exp_out)
  );

  integer cycle;
  initial begin
    rst = '0;
    enable = '0;
    x_in = '0;
    rst = 1;
    #10;
    rst = 0;

    #1;
    $display("OBS exp_out=%b", exp_out);
    #10;
    $finish;
  end
endmodule
